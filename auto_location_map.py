import argparse
from itertools import chain
from math import inf, pi, sqrt, cos, radians, atan2, hypot
from os import makedirs, path
import re
from time import time, sleep, strftime
from typing import Dict, List

import requests


STYLES = {
	"background": "fill: #ffffff; stroke: none",
	"sea": "fill: #b1deff; fill-rule: evenodd; stroke: none",
	"lake": "fill: #b1deff; fill-rule: evenodd; stroke: none",
	"green": "fill: #cdf8d5; fill-rule: evenodd; stroke: none",
	"airport": "fill: #f3e7f2; fill-rule: evenodd; stroke: none",
	"airstrip": "fill: none; stroke: #d6c9d4; stroke-width: «2»; stroke-linejoin: round; stroke-linecap: butt",
	"minor_street": "fill: none; stroke: #cbc3b6; stroke-width: «0»; stroke-linejoin: round; stroke-linecap: round",
	"major_street": "fill: none; stroke: #cbc3b6; stroke-width: «1»; stroke-linejoin: round; stroke-linecap: round",
	"minor_highway": "fill: none; stroke: #dcb46e; stroke-width: «2»; stroke-linejoin: round; stroke-linecap: round",
	"major_highway": "fill: none; stroke: #dcb46e; stroke-width: «3»; stroke-linejoin: round; stroke-linecap: round",
	"railroad": "fill: none; stroke: #ea998b; stroke-width: «0»; stroke-linejoin: round; stroke-linecap: round",
	"border": "fill: none; stroke: #a8a8a8; stroke-width: 0.56; stroke-linejoin: round; stroke-linecap: square; stroke-dasharray: 0.01 1.12 0.56 1.12",
}

LAYER_ORDER = [
	"green", "airport", "airstrip", "sea", "lake", "minor_street", "major_street",
	"minor_highway", "major_highway", "railroad", "border",
]


def main():
	parser = argparse.ArgumentParser(
		description="A script to automatically generate clean, high-contrast location maps for Wikipedia based on OpenStreetMap data")
	parser.add_argument(
		"area_specifier", type=str,
		help="Either the desired coordinate bounds of the map in the format '{south}/{north}/{west}/{east}' (e.g. 40.69/40.84/-74.03/-73.93), or the name of an existing location map on the Wikimedia Commons (in which case we will use the same bounds as the existing map)")
	parser.add_argument(
		"--street-detail", choices=["0", "1", "2", "3", "4", "5", "6", "auto"], default="auto",
		help="How many layers of street detail: 0 for none, 2 for only highways, 4 for major streets but not residential streets, and 6 for all streets")
	parser.add_argument(
		"--railroads", choices=["yes", "no", "auto"], default="auto",
		help="Whether to include passenger railways on the map")
	parser.add_argument(
		"--tramways", choices=["yes", "no", "auto"], default="auto",
		help="Whether to show dedicated tramways and busways as major streets")
	parser.add_argument(
		"--walkways", choices=["yes", "no", "auto"], default="auto",
		help="Whether to show pedestrian malls as minor streets")
	parser.add_argument(
		"--parks", choices=["yes", "no", "auto"], default="auto",
		help="Whether to include parkland on the map")
	parser.add_argument(
		"--border-detail", type=int, default=0,
		help="The level of detail at which to show political borders: 0 for none, 2 for national, 4 for provincial, and so on")
	args = parser.parse_args()

	bbox, new_filename = choose_bounds(args.area_specifier)

	x_scale, y_scale = choose_scale(bbox)

	shape_types = choose_queries(
		args.border_detail, args.street_detail,
		args.railroads, args.tramways, args.walkways, args.parks, y_scale)

	data = load_data(bbox, shape_types)

	write_SVG(new_filename, bbox, x_scale, y_scale, shape_types, data)


def choose_bounds(area_specifier):
	# if the area specifier is four numbers separated by slashes
	parsing = re.fullmatch(r"([-+0-9.e]+)/([-+0-9.e]+)/([-+0-9.e]+)/([-+0-9.e]+)", area_specifier)
	if parsing is not None:
		# those numbers are the bounding box
		south, north, west, east = (float(group) for group in parsing.groups())
		bbox = BoundingBox(south, north, west, east)
		# make up a filename
		new_filename = f"Location map ({(south + north)/2:.1f},{(west + east)/2:.1f})"
	# if the area specifier is a filename
	else:
		# load that page from the Wikimedia Commons or from Wikipedia' Module space
		try:
			print("Reading the existing location map page...")
			filename = area_specifier.replace("File:", "")
			if path.splitext(filename)[1] == "":
				filename += ".png"
			bbox, page_filename = choose_bounds_from_wobpage(f"http://commons.wikimedia.org/wiki/File:{filename.replace(' ', '_')}")
		except Exception as error:
			print(error)
			try:
				print("Reading the existing module data page...")
				filename = area_specifier.replace("Module:", "").replace("Location map/data/", "")
				bbox, page_filename = choose_bounds_from_wobpage(f"http://en.wikipedia.org/wiki/Module:Location map/data/{filename.replace(' ', '_')}")
			except Exception as error:
				print(error)
				raise ValueError("I couldn't find any bounding box information anywhere.  Are you sure the filename you entered is correct?")
		print(f"The bounding box is {bbox.south}/{bbox.north}/{bbox.west}/{bbox.east}")
		# append "2" to the filename and remove the extension
		if page_filename is not None:
			filename = page_filename
		new_filename = path.splitext(filename)[0] + " 2"
	# double check that the bounds look right
	if bbox.north - bbox.south < 0:
		bbox.south, bbox.north = bbox.north, bbox.south
	if bbox.north - bbox.south > 2:
		raise ValueError("This script isn't built to handle maps that cover over 2° in latitude.")
	if bbox.east - bbox.west < 0:
		bbox.west, bbox.east = bbox.east, bbox.west
	if bbox.east - bbox.west > 5:
		raise ValueError("This script isn't built to handle maps that cover over 5° in longitude.")
	return bbox, new_filename


def choose_bounds_from_wobpage(address):
	# load the page
	page = requests.get(address, headers={
		"User-Agent": "User:Justinkunimune's automatic location map replacement script"
	})
	if page.status_code != 200:
		raise FileNotFoundError(f"The page `{address}` doesn't seem to exist.")
	if "No file by this name exists" in page or "does not have a Module page with this exact name" in page:
		raise FileNotFoundError(f"There doesn't seem to be anything at `{address}`.")
	# extract the bounding box from the page's content
	bounds = []
	for direction in [r"S|south|bottom", r"N|north|top", r"W|west|left", r"E|east|right"]:
		sentence = re.search(rf"\b({direction})\b[a-z</>\s]*[:=]\s+([-+0-9]+\.[0-9]+)(°[NSEW])?", page.text)
		if sentence is not None:
			bound = float(sentence.group(2))
			units = sentence.group(3)
			if units is not None and (units == "°S" or units == "°W"):
				bound *= -1
			bounds.append(bound)
		else:
			raise ValueError(f"I can't find the {direction} info on `{address}`.")
	south, north, west, east = bounds

	sentence = re.search(r"\bimage\b[a-z</>\s]*[:=]\s.*>([^<>/\\]+\.[A-Za-z]+)<", page.text)
	if sentence is not None:
		filename = sentence.group(1)
	else:
		filename = None

	return BoundingBox(south, north, west, east), filename


def choose_scale(bbox):
	# decide on an appropriate scale
	x_scale = 1
	y_scale = -1/cos(radians((bbox.south + bbox.north)/2))
	initial_area = (
		x_scale*(bbox.east - bbox.west)*
		y_scale*(bbox.south - bbox.north))
	desired_area = 10000  # mm²
	scale_correction = sqrt(desired_area/initial_area)
	x_scale *= scale_correction
	y_scale *= scale_correction
	return x_scale, y_scale


def choose_queries(border_detail, street_detail, railroads, tramways, walkways, parks, y_scale):
	# decide which elements to show
	if street_detail == "auto":
		if abs(y_scale) > 1200:
			num_street_layers = 6  # all streets
		elif abs(y_scale) > 600:
			num_street_layers = 5  # all but residential streets
		elif abs(y_scale) > 300:
			num_street_layers = 4  # primary and secondary streets
		elif abs(y_scale) > 150:
			num_street_layers = 3  # primary streets
		elif abs(y_scale) > 50:
			num_street_layers = 2  # only highways
		else:
			num_street_layers = 1  # only motorways
		print(f"Setting the street detail to {num_street_layers}.")
	else:
		num_street_layers = int(street_detail)
	if railroads == "auto":
		show_railroads = abs(y_scale) > 1200
	else:
		show_railroads = railroads == "yes"
	if tramways == "auto":
		show_tramways = num_street_layers >= 3 and abs(y_scale) > 300
	else:
		show_tramways = tramways == "yes"
	if walkways == "auto":
		show_walkways = num_street_layers >= 5 and abs(y_scale) > 2400
	else:
		show_walkways = walkways == "yes"
	if parks == "auto":
		show_parks = abs(y_scale) > 150
	else:
		show_parks = parks == "yes"

	# put together the tags that define the relevant data
	shape_types = {
		"sea": [
			("nwr", "natural", r"^coastline$"),
		],
		"lake": [
			("nwr", "natural", r"^water$"),
		],
		"airport": [
			("nwr", "aeroway", r"^(aerodrome|airstrip|heliport|launch_complex)$"),
		],
	}
	if num_street_layers >= 1:
		shape_types["major_highway"] = [
			("way", "highway", r"^motorway$"),
		]
	if num_street_layers >= 2:
		shape_types["minor_highway"] = [
			("way", "highway", r"^trunk$"),
		]
	if num_street_layers >= 3:
		shape_types["airstrip"] = [
			("way", "aeroway", r"^runway$"),
		]
		shape_types["major_street"] = [
			("way", "highway", r"^(primary|(motorway|trunk)_link)$"),
		]
	if num_street_layers >= 4:
		shape_types["major_street"] += [
			("way", "highway", r"^secondary$"),
		]
	if num_street_layers >= 5:
		shape_types["minor_street"] = [
			("way", "highway", r"^(tertiary|(primary|secondary|tertiary)_link)$"),
		]
	if num_street_layers >= 6:
		shape_types["minor_street"] += [
			("way", "highway", r"^(unclassified|residential|living_street)$"),
		]
	if show_tramways:
		if "major_street" not in shape_types:
			shape_types["major_street"] = []
		shape_types["major_street"] += [
			("way", "railway", r"^tram$"),
		]
	if show_walkways:
		if "minor_street" not in shape_types:
			shape_types["minor_street"] = []
		shape_types["minor_street"] += [
			("way[area!=yes]", "highway", r"^pedestrian$")
		]
	if show_railroads:
		shape_types["railroad"] = [
			("way", "railway", r"^rail$"),
		]
	if show_parks:
		shape_types["green"] = [
			("nwr", "leisure", r"^(park|dog_park|pitch|stadium|golf_course|garden|nature_reserve)$"),
			("nwr", "natural", r"^(grassland|heath|scrub|tundra|wood|wetland)$"),
			("nwr", "landuse", r"^(farmland|forest|meadow|orchard|vineyard|cemetery|recreation_ground|village_green)$"),
			("nwr[boundary=protected_area]", "protect_class", r"^1[ab]?$")
		]
	if border_detail != 0:
		shape_types["border"] = [
			("way[!admin_level]", "boundary", r"^administrative$"),
			("way[boundary=administrative]", "admin_level", fr"^[1-{border_detail}]$"),
		]

	return shape_types


def load_data(bbox, shape_types):
	# load relevant data for the relevant region from OpenStreetMap's Overpass API
	full_query = f"[out:json][bbox:{bbox.south},{bbox.west},{bbox.north},{bbox.east}]; ( "
	for query_set in shape_types.values():
		for kind, key, values in query_set:
			full_query += f'{kind}["{key}"~"{values}"]; '
			if key in ["highway", "railway", "landuse"]:  # don't forget to also query roads under construction
				full_query += f'{kind}["{key}"="construction"]["construction"~"{values}"]; '
	full_query += f"); out geom;"
	print(f"Loading data from OpenStreetMap...")
	start = time()
	response = requests.post("https://overpass-api.de/api/interpreter", data={"data": full_query})
	if response.status_code == 504:
		raise ValueError(f"The OpenStreetMap server said it was too busy to respond to us (error 504).  Wait a minute and try again.  If the problem persists, the query may be too big, in which case you would need to suppress some map features or reduce the amount of street detail.")
	elif response.status_code != 200:
		raise ValueError(f"The OpenStreetMap query failed with error code {response.status_code}.")
	end = time()
	data = response.json()
	print(f"Loaded {len(data['elements'])} shapes in {end - start:.0f} seconds.")
	return data


def write_SVG(new_filename, bbox, x_scale, y_scale, shape_types, data):
	# compose the description
	sources = {"the OpenStreetMap contributors"}
	for shape in data["elements"]:
		if "attribution" in shape["tags"]:
			sources.add("the " + shape["tags"]["attribution"])
	attribution = " and ".join(sorted(sources))
	description = (
		f'A location map of the region with latitudes between {bbox.south}° and {bbox.north}°, '
		f'and longitudes between {bbox.west}° and {bbox.east}°.  '
		f'Equirectangular projection, scale 1 : {round(-111111111/y_scale, -3):,.0f}.  '
		f'The data for this map come from {attribution}, and are made available by OpenStreetMap '
		f'under the <a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License</a>.  '
		f'It was accessed on {strftime("%Y %b %d")}.  The map itself was generated by '
		f'<a href="https://github.com/jkunimune/auto-location-map">a Python script written by Justin Kunimune</a>.')
	description = re.sub(r"([0-9]),([0-9])", "\\1 \\2", description)  # use spaces for thousands grouping
	description = re.sub(r" -([0-9])", " −\\1", description)  # use unicode minus symbol
	wikitext_description = re.sub(r'<a href="([^"]+)">([^<]+)</a>', '[\\1 \\2]', description)
	print(f"Recommended description:\n\t{wikitext_description}")

	# compose the stylesheet
	stylesheet = f"\t\t.background {{ {STYLES['background']} }}\n"
	for shape_type in shape_types:
		stylesheet += f"\t\t.{shape_type} {{ {STYLES[shape_type]} }}\n"
	# choose the line thicknesses
	thicknesses = [1.12, 0.84, 0.56, 0.35]
	for i in range(4):
		if f"«{i}»" in stylesheet:
			stylesheet = stylesheet.replace(f"«{i}»", f"{thicknesses.pop()}")

	# write the file
	print("Writing the SVG file...")
	width = x_scale*(bbox.east - bbox.west)
	height = y_scale*(bbox.south - bbox.north)
	makedirs("maps", exist_ok=True)
	with open(f"maps/{new_filename}.svg", "w", encoding="utf-8") as file:
		# write the header
		file.write(
			f'<?xml version="1.0" encoding="UTF-8"?>\n'
			f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.2f}mm" height="{height:.2f}mm" viewBox="0 0 {width:.2f} {height:.2f}">\n'
			f'\t<title>{new_filename}</title>\n'
			f'\t<desc>\n\t\t{description}\n\t</desc>\n'
			f'\t<style>\n{stylesheet}\t</style>\n'
			f'\t<rect class="background" x="0" y="0" width="100%" height="100%" />\n'
		)

		# for each type of data, in order
		for shape_type in LAYER_ORDER:
			if shape_type not in shape_types:
				continue

			# pull out the shapes that belong to that particular type
			shapes = []
			for shape in data["elements"]:
				if shape["type"] != "node":
					for kind, key, values in shape_types[shape_type]:
						if key in shape["tags"]:
							if re.match(values, shape["tags"][key]) is not None:
								shapes.append(shape)
							elif shape["tags"][key] == "construction":  # don't forget to also get the under construction features
								if "construction" in shape["tags"] and re.match(values, shape["tags"]["construction"]) is not None:
									shapes.append(shape)
			if len(shapes) == 0:
				continue

			# pull out the geometry and post-process it into nice polygons
			paths = []
			for shape in shapes:
				if shape["type"] == "way":
					paths.append([shape["geometry"]])
				elif shape["type"] == "relation":
					path = []
					for member in shape["members"]:
						if "geometry" in member:
							path.append(member["geometry"])
					paths.append(path)
				else:
					raise TypeError(shape["type"])
			# stitch the loaded paths together as necessary
			if shape_type == "sea":  # for coastlines this is especially involved
				paths = close_polygon(consolidate_all_polygons(paths), bbox)
			elif shape_type == "border":
				paths = consolidate_all_polygons(purge_duplicate_paths(paths))
			elif "fill: none" in STYLES[shape_type]:
				paths = consolidate_all_polygons(paths)
			else:
				paths = consolidate_multipolygons(purge_small_polygons(paths, x_scale, y_scale))

			# convert it to SVG paths
			file.write(f'\t<g class="{shape_type}">\n')
			for path in paths:
				path_string = ""
				for segment in path:
					for i, point in enumerate(segment):
						command = "M" if i == 0 else "L"
						x = x_scale*(point["lon"] - bbox.west)
						y = y_scale*(point["lat"] - bbox.north)
						path_string += f"{command}{x:.2f},{y:.2f} "
				file.write(f'\t\t<path d="{path_string}" />\n')
			file.write(f'\t</g>\n')
		file.write("</svg>\n")
	print(f"Saved the map to `maps/{new_filename}.svg`!")


def consolidate_multipolygons(paths):
	finished_paths = []
	for path in paths:
		finished_segments = []
		pending_segments = path[:]
		while len(pending_segments) > 0:
			# examine an arbitrary open segment
			last_segment = pending_segments.pop()
			# if it's already closed, we're done here
			if last_segment[0] == last_segment[-1]:
				finished_segments.append(last_segment)
				continue
			# otherwise, search for another segment that starts or ends with its endpoint
			next_segment = None
			for segments in [pending_segments, finished_segments]:
				for i in range(len(segments)):
					if segments[i][0] == last_segment[-1]:
						next_segment = segments.pop(i)
						break
					elif segments[i][-1] == last_segment[-1]:
						next_segment = segments.pop(i)[::-1]
						break
				if next_segment is not None:
					break
			# if no one starts with its endpoint, consider it finalized for now
			if next_segment is None:
				finished_segments.append(last_segment)
			# if you found another one that starts with its endpoint, stick them together and add that to the queue
			else:
				pending_segments.append(last_segment + next_segment)
		# when you run out of segments, you're done
		finished_paths.append(finished_segments)
	return finished_paths


def consolidate_all_polygons(paths):
	megapath = list(chain(*paths))
	megapath = consolidate_multipolygons([megapath])[0]
	return [[part] for part in megapath]


def close_polygon(paths, bbox):
	# define this little utility function real quick
	def angular_distance(point_A, point_B):
		θ_A = atan2(
			point_A["lat"] - (bbox.north + bbox.south)/2,
			point_A["lon"] - (bbox.east + bbox.west)/2)
		θ_B = atan2(
			point_B["lat"] - (bbox.north + bbox.south)/2,
			point_B["lon"] - (bbox.east + bbox.west)/2)
		if θ_A >= θ_B:
			return θ_A - θ_B
		else:
			return θ_A - θ_B + 2*pi

	# first, add the corners to the set of segments to stitch together
	open_segments = [
		[{"lat": bbox.north, "lon": bbox.east}],
		[{"lat": bbox.north, "lon": bbox.west}],
		[{"lat": bbox.south, "lon": bbox.east}],
		[{"lat": bbox.south, "lon": bbox.west}],
	] + [path[0] for path in paths]
	# pull out any segments that are already closed
	closed_segments = []
	for i in reversed(range(4, len(open_segments) - 1)):
		if open_segments[i][0] == open_segments[i][-1]:
			closed_segments.append(open_segments.pop(i))
	# then, pull off arbitrary open segments and try to complete them
	while len(open_segments) > 0:
		new_closed_segment = open_segments[-1]
		while True:
			next_segment = min(
				open_segments,
				key=lambda segment: angular_distance(new_closed_segment[-1], segment[0])
			)
			if next_segment == new_closed_segment:
				open_segments.remove(new_closed_segment)
				if len(new_closed_segment) > 1:
					closed_segments.append(new_closed_segment)
				break
			else:
				open_segments.remove(next_segment)
				new_closed_segment += next_segment

	return [closed_segments]


def purge_duplicate_paths(paths):
	# first, dump all of the path parts into one bin of path parts
	paths = list(chain(*paths))
	# then look for identical path parts
	for i in reversed(range(len(paths))):
		for j in range(i):
			if paths[i] == paths[j]:
				paths.pop(i)
				break
	# then run a quick consolidation algorithm on what's left
	return [[path] for path in paths]


def purge_small_polygons(paths, x_scale, y_scale):
	# remove paths that have very small bounding boxen
	for i in reversed(range(len(paths))):
		path = paths[i]
		x_min, x_max = inf, -inf
		y_min, y_max = inf, -inf
		for part in path:
			for point in part:
				x = x_scale*point["lon"]
				y = y_scale*point["lat"]
				if x < x_min:
					x_min = x
				if x > x_max:
					x_max = x
				if y < y_min:
					y_min = y
				if y > y_max:
					y_max = y
		size = hypot(x_max - x_min, y_max - y_min)
		if size < 1:
			paths.pop(i)
	return paths


class BoundingBox:
	def __init__(self, south, north, west, east):
		self.south = south
		self.north = north
		self.west = west
		self.east = east


if __name__ == "__main__":
	main()

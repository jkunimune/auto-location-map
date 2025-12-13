import argparse
from itertools import chain
from math import pi, sqrt, cos, radians, atan2
from os import makedirs, path
import re
from time import time, sleep
from typing import Dict, List

import requests


RETRY_TIME = 5  # seconds


def main():
	parser = argparse.ArgumentParser(
		description="A script to automatically generate clean, high-contrast location maps for Wikipedia based on OpenStreetMap data")
	parser.add_argument(
		"area_specifier", type=str,
		help="Either the desired coordinate bounds of the map in the format '{west}/{south}/{east}/{north}' (e.g. 40.84/-74.03/40.69/-73.93), or the name of an existing location map on the Wikimedia Commons (in which case we will use the same bounds as the existing map)")
	parser.add_argument(
		"--major_streets", choices=["yes", "no", "auto"], default="auto",
		help="Whether to include major streets on the map")
	parser.add_argument(
		"--minor_streets", choices=["yes", "no", "auto"], default="auto",
		help="Whether to include residential streets on the map")
	parser.add_argument(
		"--railroads", choices=["yes", "no", "auto"], default="auto",
		help="Whether to include passenger railways on the map")
	parser.add_argument(
		"--parks", choices=["yes", "no", "auto"], default="auto",
		help="Whether to include parkland on the map")
	args = parser.parse_args()

	bbox, new_filename = choose_bounds(args.area_specifier)

	x_scale, y_scale = choose_scale(bbox)

	shape_types = choose_queries(
		args.major_streets, args.minor_streets, args.railroads, args.parks, x_scale)

	data = load_data(bbox, shape_types)

	write_SVG(new_filename, bbox, x_scale, y_scale, shape_types, data)


def choose_bounds(area_specifier):
	# if the area specifier is four numbers separated by slashes
	parsing = re.fullmatch(r"([-+0-9.e]+)/([-+0-9.e]+)/([-+0-9.e]+)/([-+0-9.e]+)", area_specifier)
	if parsing is not None:
		# those numbers are the bounding box
		west, south, east, north = (float(group) for group in parsing.groups())
		bbox = BoundingBox(west, south, east, north)
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
			bbox = choose_bounds_from_wobpage(f"http://commons.wikimedia.org/wiki/File:{filename.replace(' ', '_')}")
		except Exception as error:
			print(error)
			try:
				print("Reading the existing module data page...")
				filename = area_specifier.replace("Module:", "").replace("Location map/data/", "")
				bbox = choose_bounds_from_wobpage(f"http://en.wikipedia.org/wiki/Module:Location map/data/{filename.replace(' ', '_')}")
			except Exception as error:
				print(error)
				raise ValueError("I couldn't find any bounding box information anywhere.")
		print(f"The bounding box is {bbox.west}/{bbox.south}/{bbox.east}/{bbox.north}")
		# append "2" to the filename and remove the extension
		new_filename = path.splitext(filename)[0] + " 2"
	# double check that the bounds look right
	if bbox.north - bbox.south < 0:
		raise ValueError("The north edge can't be south of the south edge!")
	elif bbox.north - bbox.south > 10:
		raise ValueError("This script isn't built to handle maps that cover over 10° in latitude.")
	elif bbox.east - bbox.west < 0:
		raise ValueError("The east edge can't be west of the west edge!")
	elif bbox.east - bbox.west > 20:
		raise ValueError("This script isn't built to handle maps that cover over 20° in longitude.")
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
	for direction in [["W", "left"], ["S", "bottom"], ["E", "right"], ["N", "top"]]:
		bound = None
		for name in direction:
			sentence = re.search(rf"\b{name}\b[a-z</> ]*[:=] ([-+0-9.e]+)(°[NSEW])?", page.text)
			if sentence is not None:
				bound = float(sentence.group(1))
				units = sentence.group(2)
				if units is not None and (units == "°S" or units == "°W"):
					bound *= -1
				break
		if bound is None:
			raise ValueError(f"I can't find the {'/'.join(direction)} info on `{address}`.")
		else:
			bounds.append(bound)
	west, south, east, north = bounds
	return BoundingBox(west, south, east, north)


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


def choose_queries(major_streets, minor_streets, railroads, parks, x_scale):
	# decide which elements to show
	if major_streets == "yes":
		show_major_streets = True
	elif major_streets == "no":
		show_major_streets = False
	else:
		show_major_streets = x_scale > 1000
	if minor_streets == "yes":
		show_minor_streets = True
	elif minor_streets == "no":
		show_minor_streets = False
	else:
		show_minor_streets = x_scale > 2000
	if railroads == "yes":
		show_railroads = True
	elif railroads == "no":
		show_railroads = False
	else:
		show_railroads = x_scale > 5000
	if parks == "yes":
		show_parks = True
	elif parks == "no":
		show_parks = False
	else:
		show_parks = True

	# put together the tags that define the relevant data
	shape_types = {
		"sea": [
			("nwr", "natural", r"^coastline$"),
		],
		"lake": [
			("nwr", "natural", r"^water$"),
		],
		"highway": [
			("way", "highway", r"^(motorway|trunk)$"),
		],
	}
	if show_major_streets:
		shape_types["major_street"] = [
			("way", "highway", r"^((primary|secondary)(_link)?|(motorway|trunk)_link)$"),
		]
	if show_minor_streets:
		shape_types["minor_street"] = [
			("way", "highway", r"^(tertiary|residential|living_street|busway)(_link)?$"),
		]
	if show_railroads:
		shape_types["railroad"] = [
			("way", "railway", r"^rail$"),
		]
	if show_parks:
		shape_types["green"] = [
			("nwr", "leisure", r"^(park|dog_park|pitch|stadium|golf_course|garden)$"),
			("nwr", "natural", r"^(grassland|heath|scrub|tundra|wood|wetland)$"),
			("nwr", "landuse", r"^(farmland|forest|meadow|orchard|vineyard|cemetery|recreation_ground|village_green)$"),
		]
		shape_types["sand"] = [
			("nwr", "natural", r"(sand|beach)"),
		]
		shape_types["airport"] = [
			("nwr", "aeroway", r"^(aerodrome|heliport|launch_complex)$")
		]

	return shape_types


def load_data(bbox, shape_types):
	# load relevant data for the relevant region from OpenStreetMap's Overpass API
	full_query = f"[out:json][bbox:{bbox.south},{bbox.west},{bbox.north},{bbox.east}]; ( "
	for query_set in shape_types.values():
		for kind, key, values in query_set:
			full_query += f'{kind}[{key}~"{values}"]; '
	full_query += f"); out geom;"
	print(f"Loading data from OpenStreetMap...")
	start = time()
	response = requests.post("https://overpass-api.de/api/interpreter", data={"data": full_query})
	if response.status_code != 200:
		raise ValueError(f"The OpenStreetMap query failed with error code {response.status_code}.")
	end = time()
	data = response.json()
	print(f"Loaded {len(data['elements'])} shapes in {end - start:.0f} seconds.")
	return data


def write_SVG(new_filename, bbox, x_scale, y_scale, shape_types, data):
	# generate an SVG
	print("writing the SVG file...")
	width = x_scale*(bbox.east - bbox.west)
	height = y_scale*(bbox.south - bbox.north)
	makedirs("maps", exist_ok=True)
	with open(f"maps/{new_filename}.svg", "w") as file:
		# write the header
		file.write(
			f'<?xml version="1.0" encoding="UTF-8"?>\n'
			f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">\n'
			f'\t<title>{new_filename}</title>\n'
			f'\t<desc>A location map of the region with latitudes between {bbox.south} and {bbox.north}, and longitudes between {bbox.west} and {bbox.east}.  Equirectangular projection.  The data for this map is made available by the OpenStreetMap contributors, under the Open Database License: http://opendatacommons.org/licenses/odbl/1.0/</desc>\n'
			f'\t<style>\n'
			f'\t\t.background {{ fill: #ffffff; stroke: none }}\n'
			f'\t\t.sea {{ fill: #b1deff; fill-rule: evenodd; stroke: none }}\n'
			f'\t\t.lake {{ fill: #b1deff; fill-rule: evenodd; stroke: none }}\n'
			f'\t\t.green {{ fill: #d5f5da; fill-rule: evenodd; stroke: none }}\n'
			f'\t\t.sand {{ fill: #fde8c6; fill-rule: evenodd; stroke: none }}\n'
			f'\t\t.airport {{ fill: #f0e9ed; fill-rule: evenodd; stroke: none }}\n'
			f'\t\t.major_street, .minor_street {{ fill: none; stroke: #c7b9c2; stroke-width: 0.53; stroke-linejoin: round; stroke-linecap: round }}\n'
			f'\t\t.highway {{ fill: none; stroke: #b79bad; stroke-width: 1.06; stroke-linejoin: round; stroke-linecap: round }}\n'
			f'\t\t.railroad {{ fill: none; stroke: #93898f; stroke-width: 0.53; stroke-linejoin: round; stroke-linecap: round }}\n'
			f'\t</style>\n'
			f'\t<rect class="background" x="0" y="0" width="100%" height="100%" />\n'
		)

		# for each type of data, in order
		for shape_type in ["sea", "green", "sand", "airport", "lake", "minor_street", "major_street", "highway", "railroad"]:
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
			if shape_type == "sea":  # for coastlines, don't forget to stitch them together
				paths = consolidate_all_polygons(paths, bbox)
			else:  # for other layers, you still do some stitching but it's not as complicated
				paths = consolidate_multipolygons(paths)

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
			# examine the last segment
			last_segment = pending_segments.pop()
			# and search for another segment that starts or ends with its endpoint
			next_segment = None
			for i in range(len(pending_segments)):
				if pending_segments[i][0] == last_segment[-1]:
					next_segment = pending_segments.pop(i)
					break
				elif pending_segments[i][-1] == last_segment[-1]:
					next_segment = pending_segments.pop(i)[::-1]
					break
			# if no one starts with its endpoint, or it starts with its own endpoint, we're done here
			if next_segment is None or next_segment == last_segment:
				finished_segments.append(last_segment)
			# if you found another one that starts with its endpoint, stick them together and repeat
			else:
				last_segment += next_segment
				pending_segments.append(last_segment)
		# when you run out of segments, you're done
		finished_paths.append(finished_segments)
	return finished_paths


def consolidate_all_polygons(paths, bbox):
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

	# first, run the regular consolidation algorithm on all the paths together
	megapath = list(chain(*paths))
	megapath = consolidate_multipolygons([megapath])[0]

	# first, add the corners to the set of segments to stitch together
	open_segments = [
		[{"lat": bbox.north, "lon": bbox.east}],
		[{"lat": bbox.north, "lon": bbox.west}],
		[{"lat": bbox.south, "lon": bbox.east}],
		[{"lat": bbox.south, "lon": bbox.west}],
	] + megapath
	# then, pull off arbitrary open segments and try to complete them
	closed_segments = []
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



class BoundingBox:
	def __init__(self, west, south, east, north):
		self.west = west
		self.south = south
		self.east = east
		self.north = north


if __name__ == "__main__":
	main()

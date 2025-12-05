import argparse
from math import sqrt, cos, radians
from os import makedirs, path
import re
from time import time, sleep
from typing import Dict, List
import xml.etree.ElementTree

import overpass
import requests


RETRY_TIME = 5  # seconds


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


# if the area specifier is four numbers separated by slashes
parsing = re.fullmatch(r"([-+0-9.e]+)/([-+0-9.e]+)/([-+0-9.e]+)/([-+0-9.e]+)", args.area_specifier)
if parsing is not None:
	# those numbers are the bounding box
	west, south, east, north = (float(group) for group in parsing.groups())
	# make up a filename
	new_filename = f"Location map ({(south + north)/2:.1f},{(west + east)/2:.1f})"
# if the area specifier is a filename
else:
	# load that page from the Wikimedia Commons
	filename = args.area_specifier.replace("File:", "")
	print("Reading the existing location map page...")
	commons_page = requests.get(
		f"http://commons.wikimedia.org/wiki/File:{filename.replace(' ', '_')}",
		headers={"User-Agent": "User:Justinkunimune's automatic location map replacement script"}
	)
	print(commons_page.text)
	if "No file by this name exists" in commons_page:
		raise IOError(f"I can't find a file on the Commons by the name {filename!r}.")
	# extract the bounding box from that page
	bounds = []
	for direction in ["W", "E", "S", "N"]:
		sentence = re.search(rf"{direction}: ([-+0-9.e]+)°", commons_page.text)
		if sentence is None:
			raise ValueError(f"I can't find the bounding box info for {filename!r} on its page.  Are you sure it's a location map?")
		bounds.append(float(sentence.group(1)))
	west, south, east, north = bounds
	print(f"The bounding box is {west}/{south}/{east}/{north}")
	# append "2" to the filename and remove the extension
	new_filename = path.splitext(filename)[0] + " 2"

# decide on an appropriate scale
x_scale = 1
y_scale = 1/cos(radians((south + north)/2))
initial_area = x_scale*(east - west)*y_scale*(north - south)
desired_area = 2000  # mm²
scale_correction = sqrt(desired_area/initial_area)
x_scale *= scale_correction
y_scale *= scale_correction
width = x_scale*(east - west)
height = y_scale*(north - south)

# decide which elements to show
if args.major_streets == "yes":
	show_major_streets = True
elif args.major_streets == "no":
	show_major_streets = False
else:
	show_major_streets = x_scale > 200
if args.minor_streets == "yes":
	show_minor_streets = True
elif args.minor_streets == "no":
	show_minor_streets = False
else:
	show_minor_streets = x_scale > 500
if args.railroads == "yes":
	show_railroads = True
elif args.railroads == "no":
	show_railroads = False
else:
	show_railroads = x_scale > 1000
if args.parks == "yes":
	show_parks = True
elif args.parks == "no":
	show_parks = False
else:
	show_parks = True

# load relevant data for the relevant region from OpenStreetMap's Overpass API
queries = {
	"water": [
		'way[natural~"^(water|coastline)$"]',
	],
	"highway": [
		'way[highway~"^(motorway|trunk)$"]',
	],
}
if show_major_streets:
	queries["major_street"] = [
		'way[highway~"^(primary|secondary|pedestrian)$"]',
	]
if show_minor_streets:
	queries["minor_street"] = [
		'way[highway~"^(tertiary|residential|living_street|busway)$"]',
	]
if show_railroads:
	queries["railroad"] = [
		'way[railway="rail"]',
	]
if show_parks:
	queries["green"] = [
		'way[leisure~"^(park|dog_park_pitch_stadium|golf_course|garden)$"]',
		'way[natural~"^(grassland|heath|scrub|tundra|wood|wetland)$"]',
		'way[landuse~"^(farmland|forest|meadow|orchard|vineyard|cemetery|recreation_ground|village_green)$"]',
	]
	queries["sand"] = [
		'way[natural~"^(sand|beach)$"]',
	]

api = overpass.API()

# generate an SVG
print("writing the SVG file...")
makedirs("maps", exist_ok=True)
with open(f"maps/{new_filename}.svg", "w") as file:
	# write the header
	file.write(
		f'<?xml version="1.0" encoding="UTF-8"?>\n'
		f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">\n'
		f'\t<title>{new_filename}</title>\n'
		f'\t<desc>A location map of the region with latitudes between {south} and {north}, and longitudes between {west} and {east}.  Equirectangular projection.  The data for this map is made available by the OpenStreetMap contributors, under the Open Database License: http://opendatacommons.org/licenses/odbl/1.0/</desc>\n'
		f'\t<style>\n'
		f'\t\t.background {{ fill: #ffffff; stroke: none }}\n'
		f'\t\t.water {{ fill: #b1deff; stroke: none }}\n'
		f'\t\t.green {{ fill: #d5f5da; stroke: none }}\n'
		f'\t\t.sand {{ fill: #fde8c6; stroke: none }}\n'
		f'\t\t.major_street, .minor_street {{ fill: none; stroke: #c7b9c2; stroke-width: 0.35; stroke-linejoin: round }}\n'
		f'\t\t.highway {{ fill: none; stroke: #b79bad; stroke-width: 0.70; stroke-linejoin: round }}\n'
		f'\t\t.railroad {{ fill: none; stroke: #93898f; stroke-width: 0.35; stroke-linejoin: round }}\n'
		f'\t</style>\n'
	)

	# for each type of data
	for key in ["water", "green", "sand", "minor_street", "major_street", "highway", "railroad"]:
		if key not in queries:
			continue

		# query it from OpenStreetMap
		print(f"Loading '{key}' data from OpenStreetMap...")
		start = time()
		full_query = f"("
		for query_component in queries[key]:
			full_query += f"{query_component}({south},{west},{north},{east});"
		full_query += ");"
		data = None
		while data is None:
			try:
				data = api.get(full_query, verbosity="geom")
			except overpass.errors.ServerLoadError:
				sleep(RETRY_TIME)
		end = time()
		print(f"Loaded {len(data['features'])} features in {end - start:.0f} seconds.")

		if len(data["features"]) == 0:
			continue

		# convert it to SVG paths
		print(f"Adding '{key}' data to the SVG...")
		file.write(f'\t<g class="{key}">\n')
		for way in data["features"]:
			nodes = way["geometry"]["coordinates"]
			if type(nodes[0][0]) is float:
				nodes = [nodes]  # for some reason the node list is sometimes 2D and sometimes 3D so make it 3D always
			path_string = ""
			for section in nodes:
				for i, (longitude, latitude) in enumerate(section):
					command = "M" if i == 0 else "L"
					x = x_scale*(longitude - west)
					y = y_scale*(north - latitude)
					path_string += f"{command}{x:.2f},{y:.2f} "
			file.write(f'\t\t<path d="{path_string}" />\n')
		file.write(f'\t</g>\n')
		print("Done.")
	file.write("</svg>\n")
print(f"Saved the map to `maps/{new_filename}.svg`!")

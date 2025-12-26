auto location map
=================
This is a Python script to automatically generate clean, high-contrast city location maps for Wikipedia based on OpenStreetMap data.

Location maps are the backgrounds used for the "pushpin" maps you sometimes see in Wikipedia infoboxes (for example in [this 2025 version of the article "Madison Square"](https://en.wikipedia.org/w/index.php?title=Madison_Square_and_Madison_Square_Park&oldid=1321445972), captioned "Location within Manhattan").  Because they appear quite small in the article, they should be light, simple, and free of clutter.  Naive methods of generating them, such as reusing maps from other contexts or taking screenshots of OpenStreetMap, tend to produce maps that are ill-suited to this purpose.  In particular, labels are almost always unreadable at infobox scales and do nothing but add visual noise.  The purpose of this script is to provide an easy way to generate better location maps using open-source data.

# Installation

All you need is [Python 3](https://python.org) and the [Requests](https://python-requests.org) library.  Python comes preinstalled on a lot of OSs these days, but if you don't have it, you can download it from [python.org](https://python.org).  And Requests can be installed from PyPI with pip:
```bash
pip install requests
```

# Basic usage

To generate a location map, run the Python script with the desired coordinate bounds in degrees separated by slashes, in the order "{south}/{north}/{west}/{east}".  Degrees west or south should be represented as negative numbers.  I recommend putting a `--` before the thing so that the argument parser doesn't get confused if it happens to start with a negative number.  For example, for a map of downtown Manhattan, call it like this:
```bash
python auto_location_map.py -- -74.0206/40.6979/-73.9655/40.7476
```

The script will query OpenStreetMap for data in that rectangle and write an SVG file, which gets saved to the directory `maps/`.  It can be viewed with most browsers, or with a vector image editor like Inkscape or Adobe Illustrator.

Here is the result of the above command:

![Location map of Lower Manhattan showing streets, highways, and parks](https://upload.wikimedia.org/wikipedia/commons/f/f3/Location_map_Lower_Manhattan_2.svg)

Instead of passing the exact coordinates, you can also pass the name of an existing location map file or module on Wikipedia, and it will read those pages to infer the bounds.  Don't forget to use quotation marks if it contains spaces.  So for example, this will make a map that matches [File:Location map Lower Manhattan.png](https://commons.wikimedia.org/wiki/File:Location_map_Lower_Manhattan.png):
```bash
python auto_location_map.py 'Location map Lower Manhattan.png'
```
and this make a map that goes with [Module:Location map/data/United States Lower Manhattan](https://en.wikipedia.org/wiki/Module:Location_map/data/United_States_Lower_Manhattan):
```bash
python auto_location_map.py 'United States Lower Manhattan'
```

# Adjusting the maps

You can control the amount of detail in the map with command-line arguments.

To increase or decrease the number of streets, use `--street-detail`.  This is a flag between 0 and 6; lower numbers only show major streets and higher numbers include smaller streets.  If you run the script without specifying it, it will tell you what number it picked.

You can also force or suppress the inclusion of railroads by passing `--railroads=yes` or `--railroads=no`, respectively.  Similarly, you can show or hide green space by passing `--parks=yes` or `--parks=no`.  For example, if for some reason you want a railroad map of downtown Manhattan you can do this:
```bash
python auto_location_map.py --street-detail=0 --railroads=yes --parks=no 'Location map Lower Manhattan.png'
```

Finally, you can show political borders by using `--border-detail`.  This is an integer that represents the level of division to show.  `--border-detail=2` shows national borders, `--border-detail=4` shows provincial borders, `--border-detail=6` shows whatever the local equivalent of county borders is, and so on.  So to show the borough boundaries, you can do this:
```bash
python auto_location_map.py --border-detail=7 'Location map Lower Manhattan.png'
```

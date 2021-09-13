"""A tool to compute CO2 emissions from Google Maps Timeline export.

Inspired by
https://observablehq.com/@steren/your-co2-emissions-from-location-history

1. Make sure you have Google Maps Timeline enabled on your phone
   https://www.google.com/maps/timeline
2. Go to https://takeout.google.com/settings/takeout/custom/location_history,
   ask for a copy of your data
3. Check your emails, download the linked zip file
4. Install the dependencies:
   pip install python-dateutil
5. Run this tool, save the output to a CSV file:
   python3 carbon_timeline.py takeout-20210804T142059Z-001.zip > carbon.csv
6. Open in your favorite spreasheet app.
"""

import argparse
import collections
import datetime
import json
import math
import pathlib
import tempfile
import zipfile

import dateutil
from dateutil import relativedelta


# We're only counting here the emissions from the fuel burnt, not including
# the car manufacturing.
# https://www.eea.europa.eu/data-and-maps/indicators/average-co2-emissions-from-motor-vehicles-1/assessment
ROAD_KG_CO2_PER_KM = 0.120
# https://www.eea.europa.eu/publications/ENVISSUENo12/page029.html
CAR_OCCUPANCY = 1.5
# https://ourworldindata.org/travel-carbon-footprint
AIR_KG_CO2_PER_KM = 0.156
# https://ourworldindata.org/travel-carbon-footprint
# I mainly use electrified trains in western europe, should be increased if
# you use non electrified trains
RAIL_KG_CO2_PER_KM = 0.006


class CarbonTimeline:
  """Main class."""

  def __init__(self, takeout_file, resolution, debug):
    temp_dir = tempfile.TemporaryDirectory()

    file = zipfile.ZipFile(takeout_file)
    file.extractall(path=temp_dir.name)

    p = pathlib.Path(temp_dir.name)
    json_files = list(p.glob("**/*.json"))
    # json_files = list(p.glob("**/2020_*.json"))
    clean_activities = self.extract_activities(json_files)
    if debug:
      self.print_csv_activities(clean_activities)
    else:
      bucketized_activities = self.bucketize(clean_activities, resolution)
      self.print_csv_bucketized_activities(bucketized_activities)
    temp_dir.cleanup()

  def extract_activities(self, json_files):
    """From timelineObjects, extracts activities objects, convert them.

    Args:
      json_files: path to the files, one per month.

    Returns:
      A list of clean activities, with only the fields we need to compute co2.
    """
    # JSON is like
    # {"timelineObjects" :
    #   [{"activitySegment" : "a"}, {"activitySegment" : "b"}, {"other": "c"}]}
    # we just need the activity segments.
    activities = []
    for json_file in json_files:
      with json_file.open() as f:
        json_dict = json.loads(f.read())
        if "timelineObjects" in json_dict:
          json_list = json_dict["timelineObjects"]
          for my_dict in json_list:
            if "activitySegment" in my_dict:
              clean = self.clean_fields(my_dict)
              if clean is not None:
                activities.append(clean)
    activities.sort(key=lambda x: int(x["ts"]))
    return activities

  def print_csv_activities(self, clean_activities):
    """Useful for debugging."""

    print("ts, epoch, type, distance")
    for i in clean_activities:
      print("%s, %s, %s, %s" %
            (self.print_timestamp(self.parse_timestamp(int(i["ts"])),
                                  "SECOND"), i["ts"], i["type"], i["distance"]))

  def clean_fields(self, activity_segment):
    """Converts activity_segment to something usable.

    Args:
      activity_segment: dict as found in json.

    Returns:
      A cleaner dict like
      {
        ts: timestamp in ms
        distance: distance in km
        type: activity like AIR, RAIL, ROAD
      },
      None if carbon neutral,
    """
    clean = {}
    clean["ts"] = int(activity_segment["activitySegment"]["duration"][
        "startTimestampMs"])
    if "distance" not in activity_segment["activitySegment"]:
      return None
    clean["distance"] = activity_segment["activitySegment"]["distance"] // 1000
    if "activityType" not in activity_segment["activitySegment"]:
      return None
    clean["type"] = self.categorize_activity(
        activity_segment["activitySegment"]["activityType"])
    if clean["type"] is None:
      return None
    return clean

  def parse_timestamp(self, epoch):
    """Returns a timestamp from the number of ms since 1970.

    Args:
      epoch: number of milliseconds since 1970.

    Returns:
      A datetime object.
    """
    epoch = math.floor(epoch / 1000)
    ts = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    return ts

  def print_timestamp(self, timestamp, resolution):
    if resolution == "MONTH":
      return timestamp.strftime("%Y-%m")
    if resolution == "YEAR":
      return timestamp.strftime("%Y")
    if resolution == "SECOND":
      return timestamp.strftime("%Y-%m-%d %H:%M:%S%z")

  def categorize_activity(self, activity):
    """From an activity like IN_TRAIN, returns AIR, ROAD, RAIL or None."""
    if activity == "FLYING":
      return "AIR"
    if activity in ["IN_TAXI", "IN_PASSENGER_VEHICLE", "IN_VEHICLE"]:
      return "ROAD"
    if activity in ["IN_TRAIN", "IN_TRAM"]:
      return "RAIL"
    return None

  def bucketize(self, clean_activities, resolution):
    """Sum up kilometers and co2 emissions over a bucket of size resolution.

    Args:
      clean_activities: a list like [{ts, distance, type}, {...}].
      resolution: MONTH or YEAR.

    Returns:
      An OrderedDict like
      {"2021-08": {air_km: 1000, road_km: 100, rail_km: 10,
      air_co2:, road_co2:, rail_co2: }}
    """
    results = collections.OrderedDict()
    current = self.parse_timestamp(clean_activities[0]["ts"]).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)
    if resolution == "YEAR":
      current = self.parse_timestamp(clean_activities[0]["ts"]).replace(
          day=1, month=1, hour=0, minute=0, second=0, microsecond=0)
    last_timestamp = self.parse_timestamp(clean_activities[-1]["ts"])
    # Create empty entries for all months/years.
    while current < last_timestamp:
      results[self.print_timestamp(current, resolution)] = {
          "air_km": 0,
          "road_km": 0,
          "rail_km": 0,
          "air_co2": 0,
          "road_co2": 0,
          "rail_co2": 0
      }
      if resolution == "MONTH":
        current += dateutil.relativedelta.relativedelta(months=1)
      else:
        current += dateutil.relativedelta.relativedelta(years=1)

    # Sum up the distances in the right categories.
    for act in clean_activities:
      short = self.print_timestamp(self.parse_timestamp(act["ts"]), resolution)
      result = results[short]
      if act["type"] == "AIR":
        result["air_km"] = result["air_km"] + act["distance"]
      if act["type"] == "ROAD":
        result["road_km"] = result["road_km"] + act["distance"]
      if act["type"] == "RAIL":
        result["rail_km"] = result["rail_km"] + act["distance"]
      results[short] = result

    # Compute carbon footprint for each bucket.
    for unused_key, value in results.items():
      value["air_co2"] = self.kg_co2(value["air_km"], "AIR")
      value["road_co2"] = self.kg_co2(value["road_km"], "ROAD")
      value["rail_co2"] = self.kg_co2(value["rail_km"], "RAIL")
    return results

  def print_csv_bucketized_activities(self, bucketized_activities):
    print("date, air_km, road_km, rail_km, air_co2, road_co2, rail_co2")
    for key, value in bucketized_activities.items():
      print("%s, %s, %s, %s, %s, %s, %s" %
            (key, value["air_km"], value["road_km"], value["rail_km"],
             value["air_co2"], value["road_co2"], value["rail_co2"]))

  def kg_co2(self, distance, transportation):
    """Computes the kg.co2.eq cost of a trip.

    Args:
      distance: in km.
      transportation: like ROAD, AIR, RAIL.

    Returns:
      carbon footpring in kg.co2.eq
    """
    co2 = 0
    if transportation == "ROAD":
      co2 = (distance * ROAD_KG_CO2_PER_KM) / CAR_OCCUPANCY
    if transportation == "AIR":
      co2 = distance * AIR_KG_CO2_PER_KM
    if transportation == "RAIL":
      co2 = distance * RAIL_KG_CO2_PER_KM
    return math.floor(co2)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("takeout_file", help="path to the takeout export file")
  parser.add_argument(
      "--resolution",
      choices=["YEAR", "MONTH"],
      help="On which unit of time to compute the carbon emissions: YEAR/MONTH",
      default="MONTH")
  parser.add_argument(
      "--debug",
      help="Print all clean trips with timestamp, useful to identify weird data",
      action=argparse.BooleanOptionalAction)
  args = parser.parse_args()
  CarbonTimeline(args.takeout_file, args.resolution, args.debug)


if __name__ == "__main__":
  main()

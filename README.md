# carbon_timeline

A tool to compute CO2 emissions from Google Maps Timeline export.

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
   ```
   $ python3 carbon_timeline.py takeout-20210804T142059Z-001.zip > month.csv
   $ python3 carbon_timeline.py  --resolution=YEAR takeout-20210804T142059Z-001.zip > year.csv
   ```
6. Open in your favorite spreasheet app.


Sample usage [in French](https://abeilles-neudorf.blogspot.com/2021/09/bilan-carbone-avec-google-maps.html).

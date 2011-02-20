import logging
import urllib2
import re
import string
import cgi
import os
import time
import urllib

from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.api import urlfetch
from django.utils import simplejson

from BeautifulSoup import BeautifulSoup

class Town(db.Model):
  name = db.StringProperty()
  latlon = db.GeoPtProperty()
  postcode = db.StringProperty()


class Suburb(db.Model):
  name = db.StringProperty()
  latlon = db.GeoPtProperty()
  lga = db.StringProperty()
  parish = db.StringProperty()
  description = db.TextProperty()
  meaning = db.StringProperty(multiline=True)
  origin = db.StringProperty(multiline=True)
  history = db.StringProperty(multiline=True)
  
  
class Match(db.Model):
  name = db.StringProperty()
  town_latlon = db.GeoPtProperty()
  suburb_latlon = db.GeoPtProperty()
  town_latlon_g = db.GeoPtProperty()
  suburb_latlon_g = db.GeoPtProperty()  
  
def parse_towns(url):
  logging.info('Parsing ' + url)
  towns = []
  try:
    response = urllib2.urlopen(url)
    html = response.read()
    soup = BeautifulSoup(html)
    next = soup.find('a', {'href': 'xyz.html'})
    while next:
      next = next.nextSibling
      if next is None:
        break
      if next.string and next.string.find(' - ') > -1:
        line = next.string
        name = string.strip(line.split(' - ')[0])
        rest = line.split(' - ')[1]
        pattern = re.compile('(\d\d\.\d\d)N\s(\d\d\.\d\d[W|E])\s+(\w+)')
        matches = re.search(pattern, rest)
        if matches:
          town = Town(key_name=name.lower())
          town.name = name
          town.latlon = db.GeoPt(float(matches.group(1)), convert_lon(matches.group(2)))
          town.postcode = matches.group(3)
          towns.append(town)
      if hasattr(next, 'name'):
        if next.name == 'table':
          break
    db.put(towns)
    logging.info('Found ' + str(len(towns)))
  except urllib2.HTTPError, e:
    print e.code
    print e.read()

def convert_lon(lon):
  if lon.find('E') > 0:
    lon = float(lon.split('E')[0])
  else:
    lon = (-1 * float(lon.split('W')[0]))
  return lon
    
def parse_alltowns():
  base_url = 'http://freepages.genealogy.rootsweb.ancestry.com/~agene/locations/'
  letters = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'ij', 'kl', 'm', 'n', 'o', 'p', 'qr', 's1', 's2', 't', 'uv', 'w', 'xyz']
  for letter in letters:
    parse_towns(base_url + letter + '.html')

def parse_suburbs(url):
  suburbs = []
  try:
    response = urllib2.urlopen(url)
    feed_obj = simplejson.loads(response.read())
    if "feed" in feed_obj:
     entries = feed_obj["feed"]["entry"]
     for entry in entries:
       name = entry['gsx$placename']['$t']
       lat = convert(entry['gsx$lat']['$t'])
       lng = convert(entry['gsx$long']['$t'])
       parish = entry['gsx$parish']['$t']
       description = entry['gsx$description']['$t']
       meaning = entry['gsx$meaning']['$t']
       origin = entry['gsx$origin']['$t']
       history = entry['gsx$history']['$t']
       suburb = Suburb(key_name=name.lower(), name=name, parish=parish, description=description, meaning=meaning, origin=origin, history=history)
       suburb.latlon = db.GeoPt(lat, lng)
       suburbs.append(suburb)
    db.put(suburbs)
    logging.info('Found ' + str(len(suburbs)))
  except urllib2.HTTPError, e:
    print e.code
    print e.read()
   
       
def convert(coords):
  multiplier = 1
  csplit = coords.split('  ')
  degrees = float(csplit[0])
  if degrees < 0:
    multiplier = -1
    degrees = abs(degrees)
  minutes = float(csplit[1])
  seconds = float(csplit[2])
  return multiplier*(degrees + (minutes * 1/60) + (seconds * 1/60 * 1/60))
  
  
def parse_allsuburbs():
  urls = ['https://spreadsheets.google.com/feeds/list/0Ah0xU81penP1dEtGZERMdjZYOEUyTmJEV2lmN1ZFY3c/od6/public/values?alt=json',
          'https://spreadsheets.google.com/feeds/list/0Ah0xU81penP1dHJ0a1g5eE9zblVTaFpCTWl2MFp6cnc/od6/public/values?alt=json']
  for url in urls:
    parse_suburbs(url)
          
class ParseTownsHandler(webapp.RequestHandler):
  def get(self):
    parse_alltowns()
    self.response.out.write('All done')

class ParseSuburbsHandler(webapp.RequestHandler):
   def get(self):
     parse_allsuburbs()
     self.response.out.write('Done parsing suburbs.')

def geocodeAddress(bounds, region, address):
   base_url = 'http://maps.googleapis.com/maps/api/geocode/json?'
   values = {'sensor': 'false', 'bounds': bounds, 'region': region, 'address': address}
   url = base_url + urllib.urlencode(values)
   logging.info(url)
   try:
     response = urllib2.urlopen(url)
     data = simplejson.loads(response.read())
     if data['status'] == 'OK' and len(data['results']) > 0:
       result = data['results'][0]
       lat = result['geometry']['location']['lat']
       lng = result['geometry']['location']['lng']
       return db.GeoPt(lat, lng)
     else:
       logging.info(data['status'])
   except urllib2.HTTPError, e:
     print url
     print e.code
     print e.read()
   return None
   
class CompareHandler(webapp.RequestHandler):
  def get(self):
    matches = []
    suburbs = Suburb.all().fetch(1800)
    for suburb in suburbs:
      keyname = suburb.key().name()
      town = Town.get_by_key_name(keyname)
      if town:
        match = Match(key_name=keyname)
        match.name = suburb.name
        match.town_latlon = town.latlon
        match.suburb_latlon = suburb.latlon
        matches.append(match)
    db.put(matches)
    logging.info('Found ' + str(len(matches)))
    
class GeocodeHandler(webapp.RequestHandler):
  def get(self):
    matches = Match.all().fetch(300)
    for match in matches:
      bounds_uk = '49.58,-10.85|59.49,4.09'
      bounds_au = '-43.7,138.3|-24.7,159.8'
      match.town_latlon_g = geocodeAddress(bounds_uk, 'gb', match.name + ',UK')
      time.sleep(.3)
      #if match.suburb_latlon_g is None:
      #  match.suburb_latlon_g = geocodeAddress(bounds_au, 'au', match.name + ',NSW,AU')
      #  time.sleep(.3)
    db.put(matches)
    
    
def getll(latlon):
  if latlon:
    return {'lat': latlon.lat, 'lng': latlon.lon}
  else:
    return {'lat': 99.99, 'lng': 99.99}
  
    
class ListHandler(webapp.RequestHandler):
  def get(self):
    matches = Match.all().fetch(300)
    match_data = []
    for match in matches:
      match_data.append({'name': match.name, 'townll': getll(match.town_latlon_g), 'suburbll': getll(match.suburb_latlon_g)})
    self.response.out.write(simplejson.dumps(match_data))

class MapHandler(webapp.RequestHandler):
  def get(self):
    path = os.path.join(os.path.dirname(__file__), 'map.html')
    self.response.out.write(template.render(path, {}))
    
    
application = webapp.WSGIApplication(
                                     [('/', MapHandler)
                                     ],
                                     debug=True)

def main():
  run_wsgi_app(application)

if __name__ == "__main__":
  main()
             
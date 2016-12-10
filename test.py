from bs4 import BeautifulSoup
import urllib.request


with urllib.request.urlopen('http://www.capitalfm.com/digital/radio/last-played-songs/') as response:
   html = response.read()


soup = BeautifulSoup(html, "lxml")
tags = soup.find_all('div', class_ = "song_wrapper", limit = 10)
songs = ***REMOVED******REMOVED***
#tags.reverse ()
for t in tags:
    name = t.find ("a", class_ = "track")
    author = t.find ("a", class_ = "first")
    if name is not None:
        songs [name.text.strip ()] = author.text.strip () if author is not None else "Unknown"

print (str (songs))

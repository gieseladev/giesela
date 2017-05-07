import re
from urllib import request

from bs4 import BeautifulSoup

from enum import Enum


class ContentType(Enum):
    IMAGE = 1
    VIDEO = 2


class Post:

    def __init__(self, id, title, upvotes, comments, content_type, content_url):
        self.id = id
        self.title = title
        self.upvotes = upvotes
        self.comments = comments
        self.content_type = content_type
        self.content_url = content_url

    @classmethod
    def from_id(cls, post_id):
        with request.urlopen("https://9gag.com/gag/" + post_id) as f:
            data = f.read().decode("utf-8")

        soup = BeautifulSoup(data, "lxml")
        post_title = soup.h2.text
        post_upvotes = int(re.sub(r"\W", "", soup.findAll(
            "span", ***REMOVED***"class": "badge-item-love-count"***REMOVED***)[0].text))
        post_comments = int(re.sub(r"\W", "", soup.findAll(
            "span", ***REMOVED***"class": "badge-item-comment-count"***REMOVED***)[0].text))

        container = soup.findAll(
            "div", ***REMOVED***"class": "badge-post-container"***REMOVED***)[0]

        post_image = container.findAll(
            "img", ***REMOVED***"class": "badge-item-img"***REMOVED***)[0]["src"]

        post_content_type = ContentType.IMAGE
        post_content_url = post_image

        post_video = container.findAll("video")
        if len(post_video) > 0:
            post_video = post_video[0].findAll(
                "source", ***REMOVED***"type": "video/webm"***REMOVED***)[0]["src"]
            post_content_type = ContentType.VIDEO
            post_content_url = post_video

        return cls(post_id, post_title, post_upvotes, post_comments, post_content_type, post_content_url)

    @property
    def hyperlink(self):
        return "https://9gag.com/gag/" + self.id

    def __repr__(self):
        return "Post(\"***REMOVED***0.id***REMOVED***\", \"***REMOVED***0.title***REMOVED***\", ***REMOVED***0.upvotes***REMOVED***, ***REMOVED***0.comments***REMOVED***, ***REMOVED***0.content_type***REMOVED***, \"***REMOVED***0.content_url***REMOVED***\")".format(self)


def get_post(post_id):
    return Post.from_id(post_id)


# print(get_post("aVq4XWy"))

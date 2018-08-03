import json
import re
from datetime import datetime
from enum import Enum
from html import unescape
from urllib import request

from bs4 import BeautifulSoup
from musicbot.config import ConfigDefaults


class ContentType(Enum):
    IMAGE = 1
    VIDEO = 2
    TEXT = 3
    GIF = 4


class Comment:

    def __init__(self, name, avatar, profile_url, content, likes, dislikes, timestamp, permalink, reply_count, content_type=ContentType.TEXT):
        self.name = name
        self.avatar = avatar
        self.profile_url = profile_url
        self.content = content
        self.likes = likes
        self.dislikes = dislikes
        self.timestamp = datetime.fromtimestamp(timestamp)
        self.permalink = permalink
        self.reply_count = reply_count
        self.content_type = content_type

    @classmethod
    def from_json(cls, json_data):
        user_data = json_data["user"]
        content_type = json_data["type"]
        content = unescape(json_data["text"])

        if content_type == "text":
            content_type = ContentType.TEXT
        elif content_type == "media":
            media = json_data["embedMediaMeta"]["embedImage"]
            if "animated" in media:
                content_type = ContentType.GIF
                content = media["animated"]["url"]
            elif "image" in media:
                content_type = ContentType.IMAGE
                content = media["image"]["url"]
            else:
                content_type = ContentType.TEXT

        return cls(user_data["displayName"], user_data["avatarUrl"], list(user_data["profileUrls"].values())[0], content, json_data["likeCount"], json_data["dislikeCount"], json_data["timestamp"], json_data["permalink"], json_data["childrenTotal"], content_type)

    @property
    def score(self):
        return self.likes - self.dislikes

    def __repr__(self):
        return "Comment({0.name}, {0.avatar}, {0.profile_url}, {0.content}, {0.likes}, {0.dislikes}, {0.timestamp})".format(self)


class Post:

    def __init__(self, id, title, upvotes, comments, content_type, content_url, comment_count):
        self.id = id
        self.title = title
        self.upvotes = upvotes
        self.comments = comments
        self.content_type = content_type
        self.content_url = content_url
        self.comment_count = comment_count

    @classmethod
    def from_id(cls, post_id):
        with request.urlopen("https://9gag.com/gag/" + post_id) as f:
            data = f.read().decode("utf-8")

        soup = BeautifulSoup(data, ConfigDefaults.html_parser)
        post_title = soup.h2.text
        post_upvotes = int(re.sub(r"\W", "", soup.findAll(
            "span", {"class": "badge-item-love-count"})[0].text))

        with request.urlopen("https://comment-cdn.9gag.com/v1/cacheable/comment-list.json?url=http%3A%2F%2F9gag.com%2Fgag%2F{}&level=2&count=10&appId=a_dd8f2b7d304a10edaf6f29517ea0ca4100a43d1b&order=score".format(post_id)) as f:
            response = json.loads(f.read().decode("utf-8"))

        post_comments = []
        for comment in response["payload"]["comments"]:
            post_comments.append(Comment.from_json(comment))

        post_comments.sort(key=lambda comment: comment.score, reverse=True)

        container = soup.findAll(
            "div", {"class": "badge-post-container"})[0]

        post_image = container.findAll(
            "img", {"class": "badge-item-img"})[0]["src"]

        post_content_type = ContentType.IMAGE
        post_content_url = post_image

        post_video = container.findAll("video")
        if len(post_video) > 0:
            post_video = post_video[0].findAll(
                "source", {"type": "video/mp4"})[0]["src"]
            post_content_type = ContentType.VIDEO
            post_content_url = post_video

        comment_count = int(re.sub(r"\W", "", soup.findAll(
            "span", {"class": "badge-item-comment-count"})[0].text))

        return cls(post_id, post_title, post_upvotes, post_comments, post_content_type, post_content_url, comment_count)

    @property
    def hyperlink(self):
        return "https://9gag.com/gag/" + self.id

    def __repr__(self):
        return "Post(\"{0.id}\", \"{0.title}\", {0.upvotes}, {0.comments}, {0.content_type}, \"{0.content_url}\")".format(self)


def get_post(post_id):
    try:
        return Post.from_id(post_id)
    except:
        raise
        return False


# print(get_post("aRm8j8y"))

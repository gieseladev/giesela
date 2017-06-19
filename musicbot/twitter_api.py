from datetime import datetime

import twitter


class User:

    def __init__(self, *, name, description, followers, id, lang, location, avatar_url, screen_name, statuses_count, url):
        self.name = name
        self.description = description
        self.followers = followers
        self.id = id
        self.lang = lang
        self.location = location
        self.avatar_url = avatar_url
        self.screen_name = screen_name
        self.statuses_count = statuses_count
        self.url = url

    @classmethod
    def from_json(cls, data):
        kwargs = ***REMOVED***
            "name": data.name,
            "description": data.description,
            "followers": data.followers_count,
            "id": data.id,
            "lang": data.lang,
            "location": data.location,
            "avatar_url": data.profile_image_url,
            "screen_name": data.screen_name,
            "statuses_count": data.statuses_count,
            "url": data.url
        ***REMOVED***

        return cls(**kwargs)

    def __repr__(self):
        return "<***REMOVED***0.name***REMOVED***>".format(self)


class Tweet:

    def __init__(self, *, created_at, like_count, hashtags, id, language, retweet_count, source, text, urls, user, mentions):
        self.created_at = created_at
        self.like_count = like_count
        self.hashtags = hashtags
        self.id = id
        self.language = language
        self.retweet_count = retweet_count
        self.source = source
        self.text = text
        self.urls = urls
        self.user = user
        self.mentions = mentions

    @classmethod
    def from_id(cls, tweet_id):
        status = api.GetStatus(tweet_id)
        kwargs = ***REMOVED***"created_at": datetime.strptime(status.created_at, "%a %b %d %H:%M:%S %z %Y"),
                  "like_count": status.favorite_count,
                  "id": tweet_id,
                  "language": status.lang,
                  "hashtags": status.hashtags,
                  "retweet_count": status.retweet_count,
                  "source": status.source,
                  "text": status.text,
                  "urls": status.urls,
                  "user": User.from_json(status.user),
                  "mentions": status.user_mentions***REMOVED***

        return cls(**kwargs)

    def __repr__(self):
        return "***REMOVED***0.user***REMOVED***: ***REMOVED***0.text***REMOVED***".format(self)


def get_tweet(tweet_id):
    return Tweet.from_id(tweet_id)


credentials = ***REMOVED***"consumer_key": "CcleNL3BCTXxGVr39fdK5SBBH", "consumer_secret": "tcF3bWoAcgRaCYOZGy4jNpzHPTdWBUL9RjtYCoqGq6Q3tm4Kbj",
               "access_token_key": "3027865895-eWngTcWlnZnZgK5HHd9FBgIW4ywEgrkdb5pHDTd", "access_token_secret": "YOakSjoSFPPIwt6kimoWLWgNuGj2tJXNSafKjMwTca1pR"***REMOVED***
api = twitter.Api(**credentials)

# print(get_tweet("862331403350011908"))

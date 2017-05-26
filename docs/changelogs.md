---
title: Changelog
description: Even the best need some changes sometimes
layout: default
---
# Changelogs
{% for post in site.posts %}
  - [{{ post.title }}]({{ site.url }}{{ post.url }})
{% endfor %}

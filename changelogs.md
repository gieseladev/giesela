---
title: Changelog
description: Even the best need some changes sometimes
layout: default
---

# Changelogs
{% for post in site.posts %}
  - [{{ post.version | default: post.title }} {% unless post.released %}[DEV]{% endunless %}]({{ site.url }}{{ post.url }})
{% endfor %}

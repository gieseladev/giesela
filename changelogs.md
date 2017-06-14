---
title: Changelog
description: Even the best need some changes sometimes
layout: default
---

# Changelogs
{% for post in site.posts %}
  - [{{ post.version | default: post.title }} {% if not post.released %}[DEV]{% endif %}]({{ site.url }}{{ post.url }})
{% endfor %}

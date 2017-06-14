---
title: Changelog
description: Even the best need some changes sometimes
layout: default
---

# Changelogs
{% for post in site.posts %}
  - [{{ post.version | default: post.title }} {% if post.development %}[DEV]{% endif %}]({{ site.url }}{{ post.url }})
{% endfor %}

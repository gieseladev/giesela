---
title: Changelog
description: Even the best need some changes every once in a while
layout: default
---

# Changelogs
{% for post in site.posts %}
  - [{{ post.version | default: post.title }} {% if post.development %}[DEV]{% endif %}{% if post.subtitle %}: **{{ post.subtitle }}**{% endif %}]({{ site.url }}{{ post.url }})
{% endfor %}

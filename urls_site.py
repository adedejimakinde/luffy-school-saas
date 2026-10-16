"""What the **public site host** serves (`settings.SITE_HOST`, the bare domain).

Classnode's own pages for a school that is not a customer yet, its
privacy notice and terms, its blog, and the sitemap that lists them, and nothing else: no API, no admin, no sign-in. The doors are linked from here and stay on
the portal, for the reason `urls_public.py` gives. Chosen by
`schools.middleware.PlatformTenantMiddleware`, which is the only thing that
routes a request here.

The blog is published posts only (`blog.views`); writing and reviewing them
happens on the portal's `/write/`, which is not routed here at all.
"""

from django.urls import path, re_path

from blog import views as blog
from website.views import homepage, privacy, sitemap, terms

urlpatterns = [
    path("", homepage, name="site-home"),
    path("privacy/", privacy, name="site-privacy"),
    path("terms/", terms, name="site-terms"),
    path("blog/", blog.index, name="site-blog"),
    path("blog/page/<int:page>/", blog.index, name="blog-page"),
    re_path(r"^blog/images/(?P<key>[0-9a-f]{32})\.webp$", blog.image, name="blog-image"),
    re_path(r"^blog/images/(?P<key>[0-9a-f]{32})-small\.webp$", blog.image_small, name="blog-image-small"),
    path("blog/<slug:slug>/", blog.post, name="blog-post"),
    # `/robots.txt` points here; `website.crawlers` answers it on every host.
    path("sitemap.xml", sitemap, name="site-sitemap"),
]

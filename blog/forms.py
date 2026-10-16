"""The editor's form, field by field: lengths, the address and the tags."""

import re

from django import forms

from . import models, workflow

_TAG = re.compile(r"^[\w][\w &'-]*$")


class PostForm(forms.Form):
    title = forms.CharField(max_length=models.TITLE_MAX, required=False)
    slug = forms.CharField(max_length=models.SLUG_MAX, required=False)
    summary = forms.CharField(max_length=models.SUMMARY_MAX, required=False, widget=forms.Textarea)
    body = forms.CharField(required=False, widget=forms.Textarea, strip=False)
    seo_title = forms.CharField(max_length=models.SEO_TITLE_MAX, required=False)
    seo_description = forms.CharField(
        max_length=models.SEO_DESCRIPTION_MAX, required=False, widget=forms.Textarea
    )
    tags = forms.CharField(max_length=200, required=False)
    cover_alt = forms.CharField(max_length=models.ALT_MAX, required=False)
    cover = forms.FileField(required=False)

    def __init__(self, *args, post=None, **kwargs):
        self.post = post
        super().__init__(*args, **kwargs)

    def clean_slug(self):
        slug = self.cleaned_data["slug"].strip().lower()
        if self.post is not None and self.post.first_published_at is not None:
            return self.post.slug
        if not slug:
            return self.post.slug if self.post is not None else ""
        problem = workflow.slug_problem(slug, self.post)
        if problem:
            raise forms.ValidationError(problem)
        return slug

    def clean_tags(self):
        tags = []
        for tag in self.cleaned_data["tags"].split(","):
            tag = " ".join(tag.split())
            if not tag:
                continue
            if len(tag) > models.TAG_MAX or not _TAG.match(tag):
                raise forms.ValidationError(
                    "A tag is a word or two, 30 letters at most, separated by commas."
                )
            if tag.casefold() not in {t.casefold() for t in tags}:
                tags.append(tag)
        if len(tags) > models.TAGS_MAX:
            raise forms.ValidationError("Five tags at most.")
        return tags

    def values(self) -> dict:
        """What `blog.workflow.save()` writes: every field but the cover's file."""
        return {
            name: value for name, value in self.cleaned_data.items() if name != "cover"
        }


class EmailForm(forms.Form):
    email = forms.EmailField(max_length=254)


class CodeForm(forms.Form):
    email = forms.EmailField(max_length=254)
    code = forms.CharField(max_length=12)


class NoteForm(forms.Form):
    note = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)

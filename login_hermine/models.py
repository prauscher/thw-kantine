from django.db import models


class HermineChannelMessage(models.Model):
    channel = models.CharField(max_length=50)
    message = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    delay = models.DateTimeField(auto_now_add=True)
    sent = models.DateTimeField(null=True)
    error = models.TextField(blank=True)


class HermineUserMessage(models.Model):
    user = models.CharField(max_length=50)
    message = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    delay = models.DateTimeField(auto_now_add=True)
    sent = models.DateTimeField(null=True)
    error = models.TextField(blank=True)

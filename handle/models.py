from django.db import models

class Head(models.Model):
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255) # Stored as plain text for consistency with other parts of the app

    def __str__(self):
        return self.email

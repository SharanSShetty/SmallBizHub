from social_core.backends.google import GoogleOAuth2

class OwnerGoogleOAuth2(GoogleOAuth2):
    name = 'owner-google-oauth2'  # Unique backend name
    
    # Use specific settings for this backend
    def get_key_and_secret(self):
        return (
            self.setting('KEY'),  # Will look for SOCIAL_AUTH_OWNER_GOOGLE_OAUTH2_KEY
            self.setting('SECRET') # Will look for SOCIAL_AUTH_OWNER_GOOGLE_OAUTH2_SECRET
        )

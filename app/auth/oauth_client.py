# -*- coding: utf-8 -*-
#
# Copyright 2018 - Swiss Data Science Center (SDSC)
# A partnership between École Polytechnique Fédérale de Lausanne (EPFL) and
# Eidgenössische Technische Hochschule Zürich (ETHZ).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This module contains the logic for obtaining, managing and refreshing
 oauth tokens.
"""

import json
import time

from oauthlib.oauth2 import WebApplicationClient
from requests_oauthlib import OAuth2Session

from .oauth_provider_app import OAuthProviderApp


class RenkuWebApplicationClient(WebApplicationClient):
    """``WebApplicationClientClass`` enriched with provider/app information and
    methods for (de-)serializing and obtaining tokens from the provider."""

    def __init__(
        self,
        *args,
        provider_app=None,
        scope=None,
        max_lifetime=None,
        _expires_at=None,
        **kwargs
    ):
        super().__init__(provider_app.client_id, *args, **kwargs)
        assert isinstance(
            provider_app, OAuthProviderApp
        ), "provider_app property must be instance of OAuthProviderApp class"
        self.provider_app = provider_app
        self.scope = scope
        self.max_lifetime = max_lifetime
        self._expires_at = _expires_at

    def get_authorization_url(self):
        """Get the authorization url to redirect the browser to."""
        authorization_url, _, _ = super().prepare_authorization_request(
            self.provider_app.authorization_endpoint
        )
        return authorization_url

    def fetch_token(self, authorization_response, **kwargs):
        """Convenience method for fetching tokens."""
        oauth_session = OAuth2Session(client=self, redirect_uri=self.redirect_url)
        oauth_session.fetch_token(
            self.provider_app.token_endpoint,
            authorization_response=authorization_response,
            client_secret=self.provider_app.client_secret,
            client_id=self.provider_app.client_id,
            include_client_id=True,
            **kwargs
        )
        self._fix_expiration_time()

    def refresh_access_token(self):
        """Convenience method for refreshing tokens."""
        self._expires_at = None
        oauth_session = OAuth2Session(client=self)
        oauth_session.refresh_token(
            self.provider_app.token_endpoint,
            client_id=self.provider_app.client_id,
            client_secret=self.provider_app.client_secret,
            include_client_id=True,
        )
        self._fix_expiration_time()

    # Note: Pickling would be much simpler here, but we don't fully control
    # what's going to be pickeled, so we choose the safer approach.
    def to_json(self):
        """Serialize a client into json."""
        serializer_attributes = [
            "token_type",
            "access_token",
            "refresh_token",
            "token",
            "scope",
            "state",
            "code",
            "redirect_url",
            "max_lifetime",
            "expires_in",
            "_expires_at",
        ]
        client_dict = {key: vars(self)[key] for key in serializer_attributes}
        client_dict["provider_app"] = self.provider_app.to_json()
        return json.dumps(client_dict)

    @classmethod
    def from_json(cls, serialized_client):
        """De-serialize a client from json."""
        client_dict = json.loads(serialized_client)
        client_dict["provider_app"] = OAuthProviderApp.from_json(
            client_dict["provider_app"]
        )
        return cls(**client_dict)

    def _fix_expiration_time(self):
        """Cap a very long (or infinite) token lifetime. Note that we
        do not modify the actual token (which is an attribute of the client
        object) but instead let the client object expire."""
        if self.max_lifetime and (
            (not self.expires_in) or (self.expires_in > self.max_lifetime)
        ):
            self._expires_at = int(time.time()) + self.max_lifetime
            self.expires_in = self.max_lifetime

    def expires_soon(self):
        """Check if the client instance expires soon."""
        return self._expires_at and self._expires_at < time.time() + 5

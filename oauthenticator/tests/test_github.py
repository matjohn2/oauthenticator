import re
import functools
import json
from io import BytesIO

from pytest import fixture, mark
from urllib.parse import urlparse, parse_qs
from tornado.httpclient import HTTPRequest, HTTPResponse
from tornado.httputil import HTTPHeaders

from ..github import GitHubOAuthenticator

from .mocks import setup_oauth_mock, no_code_test


def user_model(username):
    """Return a user model"""
    return {
        'login': username,
    }

@fixture
def github_client(client):
    setup_oauth_mock(client,
        host=['github.com', 'api.github.com'],
        access_token_path='/login/oauth/access_token',
        user_path='/user',
        token_type='token',
    )
    return client


@mark.gen_test
def test_github(github_client):
    authenticator = GitHubOAuthenticator()
    handler = github_client.handler_for_user(user_model('wash'))
    name = yield authenticator.authenticate(handler)
    assert name == 'wash'


@mark.gen_test
def test_no_code(github_client):
    yield no_code_test(GitHubOAuthenticator())


def make_link_header(urlinfo, page):
    return {'Link': '<{}://{}{}?page={}>;rel="next"'
                    .format(urlinfo.scheme, urlinfo.netloc, urlinfo.path, page)}


@mark.gen_test
def test_org_whitelist(github_client):
    client = github_client
    authenticator = GitHubOAuthenticator()

    ## Mock Github API

    teams = {
        'red': ['grif', 'simmons', 'donut', 'sarge', 'lopez'],
        'blue': ['tucker', 'caboose', 'burns', 'sheila', 'texas'],
    }

    member_regex = re.compile(r'/orgs/(.*)/members')

    def team_members(paginate, request):
        urlinfo = urlparse(request.url)
        team = member_regex.match(urlinfo.path).group(1)

        if team not in teams:
            return HTTPResponse(400, request)

        if not paginate:
            return [user_model(m) for m in teams[team]]
        else:
            page = parse_qs(urlinfo.query).get('page', ['1'])
            page = int(page[0])
            return team_members_paginated(
                team, page, urlinfo, functools.partial(HTTPResponse, request))

    def team_members_paginated(team, page, urlinfo, response):
        if page < len(teams[team]):
            headers = make_link_header(urlinfo, page + 1)
        elif page == len(teams[team]):
            headers = {}
        else:
            return response(400)

        headers.update({'Content-Type': 'application/json'})

        ret = [user_model(teams[team][page - 1])]

        return response(200,
                        headers=HTTPHeaders(headers),
                        buffer=BytesIO(json.dumps(ret).encode('utf-8')))

    ## Perform tests

    for paginate in (False, True):
        client.hosts['api.github.com'].append(
            (member_regex, functools.partial(team_members, paginate)),
        )

        authenticator.github_organization_whitelist = ['blue']

        handler = client.handler_for_user(user_model('caboose'))
        name = yield authenticator.authenticate(handler)
        assert name == 'caboose'

        handler = client.handler_for_user(user_model('donut'))
        name = yield authenticator.authenticate(handler)
        assert name is None

        # reverse it, just to be safe
        authenticator.github_organization_whitelist = ['red']

        handler = client.handler_for_user(user_model('caboose'))
        name = yield authenticator.authenticate(handler)
        assert name is None

        handler = client.handler_for_user(user_model('donut'))
        name = yield authenticator.authenticate(handler)
        assert name == 'donut'

        client.hosts['api.github.com'].pop()

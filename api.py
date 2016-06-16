#!/usr/bin/env python
# -*- coding:utf-8 -*-

from bottle import Bottle, request, HTTPResponse, debug
from datetime import datetime
import json
import MySQLdb
from MySQLdb.cursors import DictCursor
import os
import requests
from requests_oauthlib import OAuth1Session as OAuth

configfile = os.path.join(os.path.dirname(__file__), 'config.json')
with open(configfile, 'r') as f:
    cfg = json.load(f)

verb = {
    'maintenance': 'メンテナンスを行っています',
    'maintenance-will': 'メンテナンスを行います',
    'maintenance-cont': 'メンテナンスを行っています',
    'maintenance-done': 'メンテナンスを行いました',
    'event': '障害が発生しています',
    'event-will': '',
    'event-cont': '障害が発生しています',
    'event-done': '障害が発生しました'
}

application = Bottle()
post = application.post
get = application.get
put = application.put
delete = application.delete


class RequireNotSatisfiedError(Exception):
    pass


def require(keys):
    params = {}
    for key in keys:
        value = request.forms.get(key)
        if value is not None:
            params[key] = value
        else:
            raise RequireNotSatisfiedError(key)
    return params


def optional(keys):
    params = {}
    for key in keys:
        params[key] = request.forms.get(key)
    return params


def apikeyNotValid():
    response = HTTPResponse()
    response.status = 200
    response.body = json.dumps(
        {
            'message': 'api key not valid',
        }
    ) + "\n"
    return response


def badRequest(key):
    response = HTTPResponse()
    response.status = 400
    response.body = json.dumps(
        {
            'message': 'Failed',
            'BadRequest': key
        }
    ) + "\n"
    return response


def cannotSave():
    response = HTTPResponse()
    response.status = 500
    response.body = json.dumps(
        {
            'message': 'Failed',
            'Error': 'CannotSaveToDB'
        }
    ) + "\n"
    return response


def cannotTweet():
    response = HTTPResponse()
    response.status = 500
    response.body = json.dumps(
        {
            'message': 'Failed',
            'Error': 'CannotTweet'
        }
    ) + "\n"
    return response


def success():
    response = HTTPResponse()
    response.status = 200
    response.body = json.dumps(
        {
            'message': 'Success'
        }
    ) + "\n"
    return response


def get_info(id_):
    with MySQLdb.connect(
            cursorclass=DictCursor,
            **cfg['DB_INFO']) as cursor:
        cursor.execute(
            '''SELECT * FROM fault_info_log
            WHERE id=%s;
            ''',
            (id_,)
        )
        row = cursor.fetchone()
    if not row:
        row = {"": ""}
    return row


def get_all_info():
    with MySQLdb.connect(
            cursorclass=DictCursor,
            **cfg['DB_INFO']) as cursor:
        cursor.execute(
            '''SELECT * FROM fault_info_log;'''
        )
        rows = cursor.fetchall()
        return rows


def get_latest_info():
    with MySQLdb.connect(
            cursorclass=DictCursor,
            **cfg['DB_INFO']) as cursor:
        cursor.execute(
            '''SELECT * FROM fault_info_log
            ORDER BY id DESC
            limit 1;
            ''')
        row = cursor.fetchone()
        return row


def get_uri(id_):
    uri = (
        cfg['BASE_URI'] +
        'detail/' +
        str(id_)
    )
    return uri

def type_to_jp(infotype):
    if infotype == 'event':
        return '障害'
    elif infotype == 'maintenance':
        return 'メンテナンス'


def get_status(info):
    infotype = info['type']
    if info['begin'] > datetime.now():
        infotype += '-will'
    elif info.get('end') is None:
        infotype += '-cont'
    elif info.get('end') < datetime.now():
        infotype += '-done'
    status = (
        '【{0}】{1}〜{2}{3}、{4}. 影響サービス:{5} 詳細:{6}'
        .format(
            type_to_jp(info['type']),
            info['begin'],
            '' if info.get('end') is None else info.get('end'),
            '' if info.get('end') is None else 'の間に',
            verb[infotype],
            info['service'],
            get_uri(info['id'])
        )
    )
    return status


def save(params):
    with MySQLdb.connect(
            cursorclass=DictCursor,
            **cfg['DB_INFO']) as cursor:
        cursor.execute(
            '''INSERT INTO fault_info_log
            (type, service, begin, end, detail)
            VALUES (%s, %s, %s, %s, %s);
            ''',
            (
                params['type'],
                params['service'],
                params['begin'],
                params.get('end', None),
                params['detail'] if params.get('detail') is not None else ''
            )
        )
        cursor.execute(
            '''SELECT last_insert_id() AS id FROM fault_info_log;
            '''
        )
    return cursor.fetchone()


def tweet(status):
    ENDPOINT = 'https://api.twitter.com/1.1/statuses/update.json'
    CONFIG = cfg['TWITTER_INFO']
    twitter = OAuth(
        CONFIG['API_KEY'],
        CONFIG['API_SECRET'],
        CONFIG['ACCESS_TOKEN'],
        CONFIG['ACCESS_SECRET']
    )
    res = twitter.post(
        ENDPOINT,
        params={"status": status}
    )
    if res.status_code == 200:
        return True
    else:
        return False


def default_datetime_format(o):
    if isinstance(o, datetime):
        return o.strftime('%Y/%m/%d %H:%M:%S')
    else:
        raise TypeError(repr(o) + " is not JSON serializable")


def update(id_, params):
    keys = []
    values = []
    for key, value in params.iteritems():
        if value is not None:
            keys.append(key + '=%s')
            values.append(value)
    values.append(id_)
    with MySQLdb.connect(**cfg['DB_INFO']) as cursor:
        cursor.execute(
            '''UPDATE fault_info_log SET {0}
            WHERE id=%s;
            '''.format(', '.join(keys)),
            values
        )
    return True


def delete_info(id_):
    with MySQLdb.connect(**cfg['DB_INFO']) as cursor:
        cursor.execute(
            '''DELETE FROM fault_info_log WHERE id=%s;
            ''',
            id_
        )
    return True


@post('/')
def api_post_info():
    required_key = ['type', 'service', 'begin', 'apikey']
    optional_key = ['end', 'detail']
    try:
        params = require(required_key)
    except RequireNotSatisfiedError as e:
        return badRequest(e.message)
    params.update(optional(optional_key))
    if params['apikey'] != cfg['API_KEY']:
        return apikeyNotValid()
    try:
        id_ = save(params)['id']
    except:
        return cannotSave()
    if tweet(get_status(get_info(id_))):
        return success()
    else:
        return cannotTweet()


@get('/')
def api_get_info():
    response = HTTPResponse()
    all_ = request.query.get('all')
    issue = request.query.get('issue')
    if all_ in ['1', 'True', 'true']:
        rows = get_all_info()
        response.body = json.dumps(
            rows,
            default=default_datetime_format
        ) + "\n"
    elif issue is not None:
        row = get_info(issue)
        response.body = json.dumps(
            row,
            default=default_datetime_format
        ) + "\n"
    else:
        row = get_latest_info()
        response.body = json.dumps(
            row,
            default=default_datetime_format
        ) + "\n"
    return response


@put('/<id_:int>')
def api_update_info(id_):
    response = HTTPResponse()
    requred_key = ['apikey']
    optional_key = ['type', 'service', 'begin', 'end', 'detail']
    try:
        params = requrie(required_key)
    except RequiredSatisfiedError as e:
        return badRequest(e.message)
    params.update(optional(optional_key))
    tw_flg = request.forms.get('tweet', False)
    if params['apikey'] != cfg['API_KEY']:
        return apikeyNotValid()
    for value in params.values():
        if value is not None:
            if update(id_, params) and tw_flg:
                tweet(get_status(get_info(id_)))
            break
    row = get_info(id_)
    response.body = json.dumps(
        row,
        default=default_datetime_format
    )+"\n"
    return response


@delete('/<id_:int>')
def api_delete_info(id_):
    response = HTTPResponse()
    delete_info(id_)
    return response


if __name__ == '__main__':
    application.run(reloader=True, host='localhost', port=8080)

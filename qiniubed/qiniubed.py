# -*- coding:utf-8 -*-
#!/usr/bin/env python2
import logging
import re
import os
import shutil
import requests
import click
import json
import pyinotify
import pynotify
import pyperclip
from mimetypes import MimeTypes
from urlparse import urljoin
import qiniu


mime = MimeTypes()
logger = logging.getLogger()
CONFIG = os.path.expanduser('~/.qiniubed.conf')
pynotify.init("Bubble@Linux")


class qiniuClient(object):

    def __init__(self, accessKey, secretKey, bucket_name, domain, root):
        self._auth = qiniu.Auth(accessKey, secretKey)
        self._bucket = qiniu.BucketManager(self._auth)
        self._bucket_name = bucket_name
        self._domain = 'http://' + domain
        self._root = root

    def cal_key(self, file_path):
        key = re.sub('^{}'.format(self._root), '', file_path)
        key = key if key[0] != '/' else key[1:]
        return key

    def _upload_file(self, key, file_path):
        params = {'x:a': 'a'}
        upToken = self._auth.upload_token(self._bucket_name,
                                          key=key)
        ret, _ = qiniu.put_file(upToken, key, file_path,
                                params=params,
                                mime_type=mime.guess_type(file_path)[0])
        return ret

    def upload_file(self, file_path):
        key = self.cal_key(file_path)
        return self._upload_file(key, file_path)

    def get_chain(self, path):
        key = self.cal_key(path)
        url = urljoin(self._domain, key)
        return url

    def down_file(self, key, file_path):
        url = urljoin(self._domain, key)
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            d = os.path.dirname(file_path)
            if not os.path.exists(d):
                os.makedirs(d)
            with open(file_path, 'wb') as f:
                r.raw.decode_content = True
                shutil.copyfileobj(r.raw, f)
            return True
        else:
            return False

    def stat(self, key):
        ret, _ = self._bucket.stat(self._bucket_name, key)
        return ret

    def delete_file(self, file_path):
        "to do fix has bug"
        key = os.path.basename(file_path)
        print(file_path)
        ret, info = self._bucket.delete(self._bucket_name, key)
        assert ret is None
        assert info.status_code == 612

    def list(self, prefix=None, limit=20):
        bucket = self._bucket
        marker = None
        eof = False
        result = []
        while eof is False:
            ret, eof, info = bucket.list(self._bucket_name, prefix=prefix, marker=marker, limit=limit)
            marker = ret.get('marker', None)
            result.extend(ret['items'])
        if eof is not True:
            # 错误处理
            pass
        return result


class qiniudEventHandler(pyinotify.ProcessEvent):

    def __init__(self, qiniu_client, *args, **argv):
        super(qiniudEventHandler, self).__init__(*args, **argv)
        self._qiniu_client = qiniu_client

    def process_IN_CREATE(self, event):
        # 上传相应文件
        click.echo("CREATE event:%s"%event.pathname)
        if os.path.isfile(event.pathname):
            self._qiniu_client.upload_file(event.pathname)
            bubble_notify = pynotify.Notification(
                "qiniubed", "上传{}成功".format(event.pathname))
            bubble_notify.show()

    def process_IN_DELETE(self, event):
        click.echo('DELETE event:%s'%event.pathname)

    def process_IN_MODIFY(self, event):
        click.echo('MODIFY event:%s'% event.pathname)
        key = self._qiniu_client.cal_key(event.pathname)
        stat = self._qiniu_client.stat(key)
        if stat is not None and stat['hash'] != qiniu.etag(event.pathname):
            self._qiniu_client.upload_file(event.pathname)
            bubble_notify = pynotify.Notification(
                "qiniubed", "上传{}成功".format(event.pathname))
            bubble_notify.show()


def save_config(path, data):
    f = open(path, 'wb')
    json.dump(data, f)


def load_config(path):
    f = open(path, 'rb')
    return json.load(f)


class InputString(click.ParamType):
    "将空白的去掉"
    name = 'input-string'

    def convert(self, value, param, ctx):
        return str(value).replace(' ', '')

INPUTSTRING = InputString()


@click.group()
def cli():
    pass


@cli.command()
@click.option("--access_key", prompt="access_key", type=INPUTSTRING,
              help="access_key")
@click.option("--secret_key", prompt="secret_key", type=INPUTSTRING,
              help="secret_key")
@click.option("--bucket_name", prompt="bucket_name", type=INPUTSTRING,
              help="bucket_name")
@click.option("--domain", prompt="domain", type=INPUTSTRING,
              help="domain")
@click.option("--root", prompt="root", type=INPUTSTRING,
              help="root dir")
def config(access_key, secret_key, bucket_name, domain, root):
    root = os.path.realpath(root)
    data = {'access_key': access_key,
            'secret_key': secret_key,
            'bucket_name': bucket_name,
            'domain': domain,
            'root': root,
            }
    save_config(CONFIG, data)
    return data


@cli.command()
@click.option("--conf", default=CONFIG, help="config path")
@click.option("--demon", default=0, help="is sync demon")
def sync(conf, demon):
    try:
        data = load_config(conf)
    except IOError:
        raise
    for k, v in data.items():
        data[k] = v.encode('utf-8')
    qc = qiniuClient(data['access_key'], data['secret_key'],
                     data['bucket_name'], data['domain'],
                     data['root'])
    for item in qc.list():
        path = os.path.join(data['root'], item['key'])
        if (not os.path.exists(path)
            or os.path.exists(path) and qiniu.etag(path) != item['hash']
        ):
            if qc.down_file(item['key'], path):
                msg = "下载{}成功".format(path)
            else:
                msg = "下载{}失败".format(path)
            bubble_notify = pynotify.Notification("qiniuClund",
                                                  msg
                )
            bubble_notify.show()

    if demon:
        wm = pyinotify.WatchManager()
        event_flags = (pyinotify.IN_CREATE
                       |pyinotify.IN_DELETE
                       |pyinotify.IN_MODIFY)
        wm.add_watch(data['root'], event_flags, rec=True,
                     auto_add=True)
        eh = qiniudEventHandler(qc)
        notifier = pyinotify.Notifier(wm, eh)
        notifier.loop()

@cli.command()
@click.option("--path", prompt="path", help="get chain")
def chain(path):
    try:
        data = load_config(CONFIG)
    except IOError:
        raise
    for k, v in data.items():
        data[k] = v.encode('utf-8')
    qc = qiniuClient(data['access_key'], data['secret_key'],
                     data['bucket_name'], data['domain'],
                     data['root'])
    url = qc.get_chain(path)
    pyperclip.copy(url)
    click.echo(url)


if __name__ == '__main__':
    cli()

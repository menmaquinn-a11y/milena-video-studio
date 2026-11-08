# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Jareer Abdullah
import http.client
import json
import re
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app import Downloads, create_server, user_error, video_url, within_resolution

YOUTUBE = 'https://www.youtube.com/watch?v=BaW_jenozKc'


class LinkTests(unittest.TestCase):
    def test_quality_limit_works_for_portrait_and_landscape(self):
        for width, height in [(1920,1080),(1080,1920),(1280,720),(720,1280)]:
            self.assertTrue(within_resolution({"width":width,"height":height},1080))
        self.assertFalse(within_resolution({"width":3840,"height":2160},1080))
        self.assertFalse(within_resolution({"width":1080,"height":1920},720))
        self.assertTrue(within_resolution({"vcodec":"none"},720))

    def test_canonicalization_and_removal_of_tracking_and_playlist(self):
        for raw in [YOUTUBE + '&list=tracking&index=4', 'https://youtu.be/BaW_jenozKc?si=tracking',
                    'https://www.youtube.com/shorts/BaW_jenozKc', 'youtube.com/watch?v=BaW_jenozKc']:
            self.assertEqual(video_url(raw), (YOUTUBE, 'YouTube'))
        self.assertEqual(video_url('https://www.tiktok.com/@illit/video/7299999999999999999?is_from_webapp=1'),
                         ('https://www.tiktok.com/@illit/video/7299999999999999999', 'TikTok'))
        self.assertEqual(video_url('https://vm.tiktok.com/ZMabc123/')[1], 'TikTok')

    def test_rejects_private_hosts_credentials_other_domains_profiles_and_playlists(self):
        for raw in ['http://127.0.0.1:8767/api/status', 'https://localhost/video.mp4',
                    'https://youtube.com.evil.example/watch?v=BaW_jenozKc',
                    'https://www.youtube.com@127.0.0.1/watch?v=BaW_jenozKc',
                    'file:///etc/passwd', 'https://www.youtube.com/playlist?list=foo',
                    'https://www.youtube.com/@ILLIT', 'https://www.tiktok.com/@illit',
                    'https://www.youtube.com:444/watch?v=BaW_jenozKc',
                    'https://user:password@www.youtube.com/watch?v=BaW_jenozKc', None, [], '']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                video_url(raw)

    def test_platform_blocks_do_not_offer_cookie_or_auth_bypass(self):
        self.assertIn('não acessa suas contas', user_error('Sign in to confirm you are not a bot'))
        self.assertIn('bloqueou', user_error('HTTP Error 403'))


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        def worker(folder):
            # Exercises the complete queue and file movement without third-party traffic.
            code = ('import json,pathlib,time; p=pathlib.Path(__import__("sys").argv[1]); '
                    'print(json.dumps({"state":"downloading","percent":50}),flush=True); time.sleep(.08); '
                    '(p/"video.mp4").write_bytes(b"synthetic-video"); '
                    'print(json.dumps({"state":"complete","filename":"video.mp4","title":"Olá, teste!"}),flush=True)')
            return [sys.executable, '-c', code, str(folder)]
        self.server = create_server(self.root, port=0, worker_factory=worker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        self.origin = f'http://127.0.0.1:{self.port}'
        status, headers, html = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', html.decode())[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.downloads.close()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            client.request(method, path, body=json.dumps(data) if data is not None else None, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def authenticated(self):
        return {'Cookie': self.cookie, 'X-Milena-Token': self.token,
                'Origin': self.origin, 'Content-Type': 'application/json'}

    def test_rejects_cross_site_writes_and_dns_rebinding(self):
        status, _, _ = self.request('POST', '/api/downloads', {'url': YOUTUBE},
                                    {'Content-Type':'application/json'})
        self.assertEqual(status, 403)
        headers = self.authenticated()
        headers['Origin'] = 'https://untrusted.example'
        self.assertEqual(self.request('POST','/api/downloads', {'url':YOUTUBE}, headers)[0],403)
        self.assertEqual(self.request('GET','/',headers={'Host':'untrusted.example'})[0],403)
        self.assertEqual(self.request('GET','/api/status')[0],403)

    def test_complete_download_queue_and_authenticated_file_delivery(self):
        status, _, body = self.request('POST','/api/downloads',{'url':YOUTUBE,'quality':'720'},self.authenticated())
        self.assertEqual(status,202)
        key=json.loads(body)['id']
        for _ in range(100):
            status, _, body = self.request('GET','/api/status',headers={'Cookie':self.cookie})
            jobs=json.loads(body)['jobs']
            if jobs[0]['state'] in {'done','error'}:
                break
            time.sleep(.02)
        self.assertEqual(jobs[0]['state'],'done',jobs)
        self.assertNotIn(YOUTUBE,body.decode())
        final=self.root/jobs[0]['filename']
        self.assertEqual(final.read_bytes(),b'synthetic-video')
        status, headers, payload=self.request('GET','/files/'+key,headers={'Cookie':self.cookie})
        self.assertEqual((status,payload),(200,b'synthetic-video'))
        self.assertEqual(headers['Content-Type'],'video/mp4')
        self.assertEqual(self.request('GET','/files/'+key)[0],403)
        self.assertEqual(self.request('GET','/files/../../etc/passwd',headers={'Cookie':self.cookie})[0],404)

    def test_input_validation_and_no_implicit_download_on_get(self):
        before=len(self.server.downloads.list())
        self.request('GET','/api/downloads?url='+YOUTUBE,headers={'Cookie':self.cookie})
        self.assertEqual(len(self.server.downloads.list()),before)
        for data in [{'url':'https://localhost/secret','quality':'1080'},
                     {'url':YOUTUBE,'quality':['1080']}, {'url':YOUTUBE,'quality':'4k'}]:
            self.assertEqual(self.request('POST','/api/downloads',data,self.authenticated())[0],400)

    def test_originals_and_previous_downloads_not_overwritten(self):
        original=self.root/'video.mp4'
        original.write_bytes(b'original')
        self.test_complete_download_queue_and_authenticated_file_delivery()
        self.assertEqual(original.read_bytes(),b'original')


if __name__ == '__main__':
    unittest.main()

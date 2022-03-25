#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#  IkaLog
#  ======
#  Copyright (C) 2016 Takeshi HASEGAWA
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import os
import pprint
import sys
import threading
import time
import traceback
import webbrowser

import umsgpack

from datetime import datetime
from ikalog.outputs.statink.collector import StatInkCollector
from ikalog.outputs.statink.composer import StatInkComposer
from ikalog.utils.statink_uploader import UploadToStatInk
from ikalog.utils import *

_ = Localization.gettext_translation('statink', fallback=True).gettext

# s2s functions
load_json_func = None
prepare_battle_result_func = None


class StatInkPlugin(StatInkCollector):

    def on_reset_configuration(self):
        config = self.config
        config['enabled'] = False
        config['api_key'] = ''
        config['endpoint_url'] = 'https://stat.ink',
        config['dry_run'] = False
        config['debug_write_payload_to_file'] = False
        config['show_response'] = False
        config['track_inklings'] = True
        config['track_special_gauge'] = True
        config['track_special_weapon'] = True
        config['track_objective'] = True
        config['track_splatzone'] = True
        config['anon_all'] = False
        config['anon_others'] = False

        config['enable_s2s'] = False
        config['s2s_path'] = None

    def on_validate_configuration(self, config):
        boolean_params = ['enabled', 'write_payload_to_file', 'show_response', 'track_inklings',
                          'track_special_gauge', 'track_special_weapon', 'track_objective', 'track_splatzone', 'enable_s2s']
        for param in boolean_params:
            assert config.get(param) in [True, False, None]

        if config['enabled']:
            assert (not config.get('api_key') in [None, ''])
        return True

    def on_set_configuration(self, new_config):
        config = self.config
        for k in new_config:
            config[k] = new_config[k]
        self._s2s_prepare()

    def close_game_session_handler(self, context):
        """
        Callback from StatInkLogger
        """

        if not (self.config['enabled'] or self.config['dry_run']):
            # This plugin is not active.
            return False

        s2s_result = _s2s_get_latest_battle(self)  # Nintendo battle format
        s2s_result_valid = True
        try:
            battle_number = result.get('battle_number')
        except ValueError:
            s2s_result_valid = False

        if s2s_result_valid and self._s2s_last_battle_number_i:
            cond_bn = battle_number > self._s2s_last_battle_number_i
            cond_time = True
            s2s_result_valid = cond_bn and cond_time

        cond = \
            (context['game'].get('map', None) != None) or \
            (context['game'].get('rule', None) != None) or \
            (context['game'].get('won', None) != None)

        if (not cond) and (not s2s_result_valid):
            return False

        composer = StatInkComposer(self)
        payload = composer.compose_payload(context)

        if s2s_result_valid:
            s2s_payload = prepare_battle_result(
                0, [result], s_flag=False, sendgears=True)
            payload.update(s2s_payload)  # s2s result is priority

        cond_write_payload = \
            self.config['debug_write_payload_to_file'] or self.payload_file

        if cond_write_payload:
            payload_file = IkaUtils.get_file_name(self.payload_file, context)
            self.write_payload_to_file(payload, filename=payload_file)

        self.post_payload(context, payload)

    def _s2s_prepare(self):
        """
        Import splatnet2statink if needed.
        """
        if not self.config['enable_s2s']:
            IkaUtils.dprint(
                '%s: splatnet2statink intergration is not configured.' % (self))

        s2s_fullpath = os.path.join(
            self.config['s2s_path'], 'splatnet2statink.py')
        if not os.path.exists(s2s_fullpath):
            IkaUtils.dprint('%s: %s not found' % s2s_fullpath)

        # try importing
        sys.path.append(self.config['s2s_path'])
        ikalog_pwd = os.getcwd()
        try:
            os.chdir(self.config['s2s_path'])
            from splatnet2statink import prepare_battle_result, load_json
            global _prepare_battle_result_func
            global _load_json_func
            _prepare_battle_result_func = prepare_battle_result
            _load_json_func = load_json
            IkaUtils.dprint('%s: imported splatnet2statink' % (self))

        except:
            IkaUtils.dprint('%s: failed to import splatnet2statink' % (self))
            IkaUtils.dprint(
                '%s: splatnet2statink integration disabled' % (self))
            self.config['enable_s2s'] = False
            # FIXME: traceback
            # passthrough

        #result = self._s2s_get_latest_battle()
        #s2s_payload = prepare_battle_result(0, [result], s_flag=False, sendgears=True)
        # print(s2s_payload)

        os.chdir(ikalog_pwd)
        return self.config['enable_s2s']

    def _s2s_get_latest_battle(self):
        # Run splatnet2statink
        json_dict = _load_json_func(True)

        if json_dict.get('code') == 'AUTHENTICATION_ERROR':  # Not tested yet
            gen_new_cookie('auth')
            json_dict = _load_json_func(True)

        results = json_dict['results']
        return results[0]

    def write_response_to_file(self, r_header, r_body, basename=None):
        if basename is None:
            t = datetime.now().strftime("%Y%m%d_%H%M")
            basename = os.path.join('/tmp', 'statink_%s' % t)

        try:
            f = open(basename + '.r_header', 'w')
            f.write(r_header)
            f.close()
        except:
            IkaUtils.dprint('%s: Failed to write file' % self)
            IkaUtils.dprint(traceback.format_exc())

        try:
            f = open(basename + '.r_body', 'w')
            f.write(r_body)
            f.close()
        except:
            IkaUtils.dprint('%s: Failed to write file' % self)
            IkaUtils.dprint(traceback.format_exc())

    def write_payload_to_file(self, payload, filename=None):
        if filename is None:
            t = datetime.now().strftime("%Y%m%d_%H%M")
            filename = os.path.join('/tmp', 'statink_%s.msgpack' % t)

        try:
            f = open(filename, 'wb')
            umsgpack.pack(payload, f)
            f.close()
        except:
            IkaUtils.dprint('%s: Failed to write msgpack file' % self)
            IkaUtils.dprint(traceback.format_exc())

    def _post_payload_worker(self, context, payload, api_key,
                             call_plugins_later_func=None):
        url_statink_v2_battle = '%s/api/v2/battle' % self.config[
            'endpoint_url']

        # This function runs on worker thread.
        error, statink_response = UploadToStatInk(payload,
                                                  api_key,
                                                  url_statink_v2_battle,
                                                  self.config['show_response'],
                                                  (self.config['dry_run'] == 'server'))

        if not call_plugins_later_func:
            return

        # Trigger a event.
        if error:
            call_plugins_later_func(
                'on_output_statink_submission_error',
                params=statink_response, context=context
            )

        elif statink_response.get('id', 0) == 0:
            call_plugins_later_func(
                'on_output_statink_submission_dryrun',
                params=statink_response, context=context
            )

        else:
            call_plugins_later_func(
                'on_output_statink_submission_done',
                params=statink_response, context=context
            )

    def post_payload(self, context, payload, api_key=None):
        if self.config['dry_run'] == True:
            IkaUtils.dprint(
                '%s: Dry-run mode, skipping POST to stat.ink.' % self)
            return

        if self.payload_file:
            IkaUtils.dprint(
                '%s: payload_file is specified to %s, '
                'skipping POST to stat.ink.' % (self, self.payload_file))
            return

        if api_key is None:
            api_key = self.config['api_key']

        if api_key is None:
            raise('No API key specified')

        copied_context = IkaUtils.copy_context(context)
        call_plugins_later_func = \
            context['engine']['service']['call_plugins_later']

        thread = threading.Thread(
            target=self._post_payload_worker,
            args=(copied_context, payload, api_key, call_plugins_later_func))
        thread.start()

    def print_payload(self, payload):
        payload = payload.copy()

        for k in ['image_result', 'image_judge', 'image_gear']:
            if k in payload:
                payload[k] = '(PNG Data)'

        if 'events' in payload:
            payload['events'] = '(Events)'

        pprint.pprint(payload)

    def __init__(self):
        super(StatInkPlugin, self).__init__()

        self._s2s_last_battle_number_i = None
        self._s2s_last_check_time = None


class StatInk(StatInkPlugin):
    """
    Legacy Plugin interface
    """

    def __init__(self, api_key=None, track_objective=False,
                 track_splatzone=False, track_inklings=False,
                 track_special_gauge=False, track_special_weapon=False,
                 anon_all=False, anon_others=False,
                 debug=False, dry_run=False, url='https://stat.ink',
                 video_id=None, payload_file=None,
                 enable_s2s=False, s2s_path=None):
        super(StatInk, self).__init__()

        config = self.config
        config['enabled'] = not (api_key in ['', None])
        config['api_key'] = api_key
        config['endpoint_url'] = url
        config['dry_run'] = dry_run
        config['debug_write_payload_to_file'] = False
        config['show_response'] = debug
        config['track_inklings'] = track_inklings
        config['track_special_gauge'] = track_special_gauge
        config['track_special_weapon'] = track_special_weapon
        config['track_objective'] = track_objective
        config['track_splatzone'] = track_splatzone
        config['anon_all'] = anon_all
        config['anon_others'] = anon_others
        config['enable_s2s'] = enable_s2s
        config['s2s_path'] = s2s_path
        self._s2s_prepare()

        self.video_id = video_id
        self.payload_file = payload_file

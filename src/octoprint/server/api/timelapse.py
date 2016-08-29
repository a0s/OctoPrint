# coding=utf-8
from __future__ import absolute_import

__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2014 The OctoPrint Project - Released under terms of the AGPLv3 License"

from flask import request, jsonify, url_for, make_response

import octoprint.timelapse
from octoprint.settings import valid_boolean_trues

from octoprint.server import admin_permission, printer
from octoprint.server.util.flask import redirect_to_tornado, restricted_access, \
	non_caching, get_json_command_from_request, cache_all_invalidated, invalidate_all_keys_matching, \
	fully_cached
from octoprint.server.api import api
from octoprint.events import eventManager, Events

from octoprint.server import NO_CONTENT


#~~ timelapse handling

def register_event_listeners():
	def movie_done(event, payload):
		invalidate_all_keys_matching(lambda key: key.endswith("/timelapse:both") or key.endswith("/timelapse:unrendered"))

	eventManager().subscribe(Events.MOVIE_DONE, movie_done)


def _compute_etag(lm=None):
	if lm is None:
		lm = _compute_lastmodified()

	timelapse = octoprint.timelapse.current

	import hashlib
	hash = hashlib.sha1()
	hash.update(str(lm) if lm else "")
	hash.update(repr(timelapse))
	hash.update("both" if request.values.get("unrendered", "false") in valid_boolean_trues else "finished")
	return hash.hexdigest()


def _compute_lastmodified():
	last_modified_finished = octoprint.timelapse.last_modified_finished
	last_modified_unrendered = octoprint.timelapse.last_modified_unrendered

	if last_modified_finished is None or last_modified_unrendered is None:
		return None

	return max(last_modified_finished, last_modified_unrendered)


@api.route("/timelapse", methods=["GET"])
@fully_cached(key=lambda: "view:{}:{}".format(request.base_url,
                                              "both" if request.values.get("unrendered", "false") in valid_boolean_trues else "finished"),
              etag=lambda l: _compute_etag(lm=l),
              lm=_compute_lastmodified)
def getTimelapseData():
	timelapse = octoprint.timelapse.current

	config = {"type": "off"}
	if timelapse is not None and isinstance(timelapse, octoprint.timelapse.ZTimelapse):
		config["type"] = "zchange"
		config["postRoll"] = timelapse.post_roll
		config["fps"] = timelapse.fps
	elif timelapse is not None and isinstance(timelapse, octoprint.timelapse.TimedTimelapse):
		config["type"] = "timed"
		config["postRoll"] = timelapse.post_roll
		config["fps"] = timelapse.fps
		config.update({
			"interval": timelapse.interval
		})

	files = octoprint.timelapse.get_finished_timelapses()
	for file in files:
		file["url"] = url_for("index") + "downloads/timelapse/" + file["name"]

	result = dict(config=config,
	              files=files)

	if "unrendered" in request.values and request.values["unrendered"] in valid_boolean_trues:
		result.update(unrendered=octoprint.timelapse.get_unrendered_timelapses())

	return jsonify(result)


@api.route("/timelapse/<filename>", methods=["GET"])
@non_caching()
def downloadTimelapse(filename):
	return redirect_to_tornado(request, url_for("index") + "downloads/timelapse/" + filename)


@api.route("/timelapse/<filename>", methods=["DELETE"])
@cache_all_invalidated(lambda key: key.endswith("/timelapse:finished") or key.endswith("/timelapse:both"))
@restricted_access
def deleteTimelapse(filename):
	octoprint.timelapse.delete_finished_timelapse(filename)
	return getTimelapseData()


@api.route("/timelapse/unrendered/<name>", methods=["DELETE"])
@cache_all_invalidated(lambda key: key.endswith("/timelapse:finished") or key.endswith("/timelapse:both"))
@restricted_access
def deleteUnrenderedTimelapse(name):
	octoprint.timelapse.delete_unrendered_timelapse(name)
	return NO_CONTENT


@api.route("/timelapse/unrendered/<name>", methods=["POST"])
@restricted_access
def processUnrenderedTimelapseCommand(name):
	# valid file commands, dict mapping command name to mandatory parameters
	valid_commands = {
		"render": []
	}

	command, data, response = get_json_command_from_request(request, valid_commands)
	if response is not None:
		return response

	if command == "render":
		if printer.is_printing() or printer.is_paused():
			return make_response("Printer is currently printing, cannot render timelapse", 409)
		octoprint.timelapse.render_unrendered_timelapse(name)
		invalidate_all_keys_matching(lambda key: key.endswith("/timelapse:finished") or key.endswith("/timelapse:both"))

	return NO_CONTENT


@api.route("/timelapse", methods=["POST"])
@cache_all_invalidated(lambda key: key.endswith("/timelapse:finished") or key.endswith("/timelapse:both"))
@restricted_access
def setTimelapseConfig():
	if "type" in request.values:
		config = {
			"type": request.values["type"],
			"postRoll": 0,
			"fps": 25,
			"options": {}
		}

		if "postRoll" in request.values:
			try:
				postRoll = int(request.values["postRoll"])
			except ValueError:
				return make_response("Invalid value for postRoll: %r" % request.values["postRoll"], 400)
			else:
				if postRoll >= 0:
					config["postRoll"] = postRoll
				else:
					return make_response("Invalid value for postRoll: %d" % postRoll, 400)

		if "fps" in request.values:
			try:
				fps = int(request.values["fps"])
			except ValueError:
				return make_response("Invalid value for fps: %r" % request.values["fps"], 400)
			else:
				if fps > 0:
					config["fps"] = fps
				else:
					return make_response("Invalid value for fps: %d" % fps, 400)

		if "interval" in request.values:
			config["options"] = {
				"interval": 10
			}

			try:
				interval = int(request.values["interval"])
			except ValueError:
				return make_response("Invalid value for interval: %r" % request.values["interval"])
			else:
				if interval > 0:
					config["options"]["interval"] = interval
				else:
					return make_response("Invalid value for interval: %d" % interval)

		if admin_permission.can() and "save" in request.values and request.values["save"] in valid_boolean_trues:
			octoprint.timelapse.configure_timelapse(config, True)
		else:
			octoprint.timelapse.configure_timelapse(config)

	return getTimelapseData()


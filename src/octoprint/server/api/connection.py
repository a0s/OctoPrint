# coding=utf-8
from __future__ import absolute_import

__author__ = "Gina Häußge <osd@foosel.net>"
__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2014 The OctoPrint Project - Released under terms of the AGPLv3 License"

from flask import request, jsonify, make_response

from octoprint.settings import settings
from octoprint.printer import get_connection_options
from octoprint.server import printer, printerProfileManager, NO_CONTENT, NOT_MODIFIED
from octoprint.server.api import api
from octoprint.server.util.flask import restricted_access, get_json_command_from_request, \
	etagged, lastmodified, conditional, check_etag_and_lastmodified, no_browser_caching
import octoprint.util as util


from octoprint.server.api.printer_profiles import compute_etag as pp_compute_etag
from octoprint.server.api.printer_profiles import compute_lastmodified as pp_compute_lastmodified


def compute_etag(lm=None):
	pp_etag = pp_compute_etag(lm)
	options = get_connection_options()
	state, port, baudrate, printer_profile = printer.get_current_connection()

	import hashlib
	hash = hashlib.sha1()
	hash.update(pp_etag)
	hash.update(",".join(sorted(options["ports"])))
	hash.update(str(state))
	hash.update(port if port else "")
	hash.update(str(baudrate))
	hash.update(printer_profile.get("id", "") if printer_profile else "")
	return hash.hexdigest()

def compute_lastmodified():
	return pp_compute_lastmodified()

def check_conditional():
	lm = compute_lastmodified()
	if not lm:
		return False

	return check_etag_and_lastmodified(compute_etag(lm), lm)


@api.route("/connection", methods=["GET"])
@conditional(lambda: check_conditional(), NOT_MODIFIED)
@etagged(lambda _: compute_etag())
@lastmodified(lambda _: compute_lastmodified())
@no_browser_caching()
def connectionState():
	state, port, baudrate, printer_profile = printer.get_current_connection()
	current = {
		"state": state,
		"port": port,
		"baudrate": baudrate,
		"printerProfile": printer_profile["id"] if printer_profile is not None and "id" in printer_profile else "_default"
	}

	return jsonify({"current": current, "options": _get_options()})


@api.route("/connection", methods=["POST"])
@restricted_access
def connectionCommand():
	valid_commands = {
		"connect": [],
		"disconnect": [],
		"fake_ack": []
	}

	command, data, response = get_json_command_from_request(request, valid_commands)
	if response is not None:
		return response

	if command == "connect":
		connection_options = get_connection_options()

		port = None
		baudrate = None
		printerProfile = None
		if "port" in data.keys():
			port = data["port"]
			if port not in connection_options["ports"] and port != "AUTO":
				return make_response("Invalid port: %s" % port, 400)
		if "baudrate" in data.keys():
			baudrate = data["baudrate"]
			if baudrate not in connection_options["baudrates"] and baudrate != 0:
				return make_response("Invalid baudrate: %d" % baudrate, 400)
		if "printerProfile" in data.keys():
			printerProfile = data["printerProfile"]
			if not printerProfileManager.exists(printerProfile):
				return make_response("Invalid printer profile: %s" % printerProfile, 400)
		if "save" in data.keys() and data["save"]:
			settings().set(["serial", "port"], port)
			settings().setInt(["serial", "baudrate"], baudrate)
			printerProfileManager.set_default(printerProfile)
		if "autoconnect" in data.keys():
			settings().setBoolean(["serial", "autoconnect"], data["autoconnect"])
		settings().save()
		printer.connect(port=port, baudrate=baudrate, profile=printerProfile)
	elif command == "disconnect":
		printer.disconnect()
	elif command == "fake_ack":
		printer.fake_ack()

	return NO_CONTENT

def _get_options():
	connection_options = get_connection_options()
	profile_options = printerProfileManager.get_all()
	default_profile = printerProfileManager.get_default()

	options = dict(
		ports=connection_options["ports"],
		baudrates=connection_options["baudrates"],
		printerProfiles=[dict(id=printer_profile["id"],
		                      name=printer_profile.get("name", printer_profile["id"])) for printer_profile in profile_options.values() if "id" in printer_profile],
		portPreference=connection_options["portPreference"],
		baudratePreference=connection_options["baudratePreference"],
		printerProfilePreference=default_profile["id"] if "id" in default_profile else None
	)

	return options

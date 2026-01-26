<?php

include("header.inc.php");

// Updates

html("<p><font color=\"red\">");
switch(getvar("update"))
	{
	case "database":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin update-game-database"));
		break;
	case "system":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin apt-get-upgrade"));
		break;
	case "poweroff":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin poweroff"));
		break;
	case "restart-ntpd":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin restart-ntpd"));
		break;
	}
html("</font></p>");

section(3, "Installation");

// table?
html("<table border=\"1\">");
html("<tr><td>");
text("Device Model:");
html("</td><td>");
// FIXME: make this a function of /usr/local/bin/retrode-admin
text(str_replace(chr(0), '', file_get_contents("/proc/device-tree/model")));
html(" <a href=\"$here?update=poweroff\">Power Off</a> ");
html("</td></tr>");

html("<tr><td>");
text("Current OS Version:");
html("</td><td>");
// FIXME: make this a function of /usr/local/bin/retrode-admin
text(callcmd("fgrep VERSION= /etc/os-release | sed 's/VERSION=//' | sed 's/\"//g'; cat /etc/debian_version"));
// Links auf offizielles Debian Repo
// oder Link auf ein Wiki
html("</td></tr>");

html("<tr><td>");
text("OS Creation Date:");
html("</td><td>");
text(callcmd("sudo /usr/local/bin/retrode-admin creation-date"));
// Link auf makesd und/oder den Befehl
// created by '<a ref=...>makesd</a>...'
html("</td></tr>");

html("<tr><td>");
text("Last OS Update:");
html("</td><td>");
text(callcmd("sudo /usr/local/bin/retrode-admin last-os-update"));
echo " <a href=\"$here?update=system\">Update OS</a> ";
html("</td></tr>");

html("<tr><td>");
text("Current Kernel Version:");
html("</td><td>");
// FIXME: make this a function of /usr/local/bin/retrode-admin
text(callcmd("uname -a"));
// Links auf kernel Repo
html("</td></tr>");

html("<tr><td>");
text("Last Game Database Update:");
html("</td><td>");
// FIXME: make this a function of /usr/local/bin/retrode-admin
text(callcmd("date -r /usr/local/games/oscr/README.md '+%Y-%m-%d %H:%M:%S'"));
echo " <a href=\"$here?update=database\">Update Game Database</a> ";
// Links auf Game Database: https://github.com/sanni/cartreader/tree/master/sd
html("</td></tr>");

html("<tr><td>");
text("Internet access:");
html("</td><td>");

// FIXME: make this a function of /usr/local/bin/retrode-admin

function ping($message, $address)
{
// or should we filter "100% packet loss?" and rtt?
// ping | fgrep loss | cut -d ' ' -f 6
	$str=callcmd("timeout 1s ping -q -c 1 $address | fgrep PING");
	if($str)
		text("$message".$str);
	else
		{ html("<font color=\"red\">"); text("$message"."not reachable"); html("</font>"); }
}

ping("Host PC: ", "192.168.0.200");
html("<br>");
ping("Debian:  ", "archive.debian.org");
html("<br>");
ping("LetuxOS: ", "www.letux.org");
html("<br>");
ping("OSCR:    ", "github.com");	// for OSCR Game Database updates
html("</td></tr>");

html("</table>");

// WLAN

$ssid=trim(getvar('ssid'));		// from <input> or connect link
$password=trim(getvar("password"));	// from <input>

if (true)
{
// check if wlan exists (e.g. /sys/class/net/wlan* or search ifconfig -a)
// find interface number through e.g. iwconfig 2>&1 | fgrep 'wlan'
// FIXME: detect/report this through /usr/local/bin/retrode-wlan status -> "no WiFi"

section(3, "WLAN Configuration");

html("<p><font color=\"red\">");
switch(getvar("wlan"))
{
	case "Connect":
		if(!$ssid)
			{
			text("Connect: Missing SSID");
			break;
			}
		$cmd="sudo /usr/local/bin/retrode-wlan connect".($password?" -p '$password'":"")." $ssid'";
		text(callcmd($cmd));
		break;
	case "Disconnect":
		$cmd="sudo /usr/local/bin/retrode-wlan disconnect";
		text(callcmd($cmd));
		break;
	case "Access Point Mode":
		$cmd="sudo /usr/local/bin/retrode-wlan connect -a";
		text(callcmd($cmd));
		break;
}
html("</font></p>");

$str=callcmd("sudo /usr/local/bin/retrode-wlan status");	// STATUS SSID MAC IP4 IP6
// text($str);
$status=explode(',', $str);

$connected=trim($status[0]);
$thessid=trim($status[1]);
$apmac=trim($status[2]);
$mac=trim($status[3]);
$ip4=trim($status[4]);
$ip6=trim($status[5]);

echo "<table border=\"1\">";
if($connected != "connected")
	{
	echo "<tr><td>SSID</td><td><input name=\"ssid\" value=\"$ssid\" width=\"20\"></input>";
	echo " <input type=\"submit\" name=\"wlan\" value=\"Connect\"></input></td></tr>";
// add java script to toggle type between "password" and "text" to unhide the password
	echo "<tr><td>WPA-Key</td><td><input type=\"password\" name=\"password\" value=\"$password\" width=\"20\"></input></td></tr>";
	}
else
	{
	echo "<tr><td>SSID</td><td>"; text($thessid);
	echo " <input type=\"submit\" name=\"wlan\" value=\"Disconnect\"></input></td></tr>";
	}

echo "<tr><td>IP4 Address</td><td>"; text($ip4); echo "</td></tr>";
echo "<tr><td>IP6 Address</td><td>"; text($ip6); echo "</td></tr>";
echo "<tr><td>MAC Address</td><td>"; text($mac); echo " <input type=\"submit\" name=\"wlan\" value=\"Access Point Mode\"></input></td></tr>";
// echo "<tr><td>Frequency</td><td>2.4 GHz</td></tr>";		// ?
echo "</table>";
}

if (true)	// check if wlan exists...
{
// this also needs root permissions!
// see: https://stackoverflow.com/questions/67292960/how-to-run-a-shell-as-root-from-php-apache
section(3, "WLAN Networks");
$str=callcmd("sudo /usr/local/bin/retrode-wlan list");
// text($str);

html("<table border=\"1\">");
html("<tr><th>SSID</th><th>Frequency</th><th>dBm</th></tr>");

// potentially sort by dBm
$line=strtok($str, "\n");
while($line !== false)
{
	// text($line);
	// split: 2c:91:ab:e2:ce:d6 SSID 2437 -68.00 dBm 1.0* 2.0* 5.5* 11.0* 6.0* 9.0 12.0* 18.0
	$matches=explode(" ", $line);
	$mac=$matches[0];
	$ssid=$matches[1];
	$mhz=$matches[2];
	$dbm=$matches[3];
	html("<tr>");
	html("<td>"); weblink($ssid, "?ssid=$ssid"); html("</td>");
	html("<td>"); text(sprintf("%.3f GHz", $mhz/1000.0)); html("</td>");
	html("<td>"); text(sprintf("%.0f dBm", $dbm)); html("</td>");
	html("</tr>");
	$line = strtok("\n");
}
html("</table>");
}

section(3, "Language and Time Zone");

html("... hier sollte der User die Time-Zone und Language dieser Webseiten einstellen können - ausser wir holen das (zumindest die Language) aus den Browser-Request-Daten. Alternativ könnte das alles in Cookies gesetzt werden.");

html(" <a href=\"$here?update=restart-ntpd\">Restart NTP daemon</a> ");

// Buttons:
//   Scan
//   Connect

include("footer.inc.php");
?>

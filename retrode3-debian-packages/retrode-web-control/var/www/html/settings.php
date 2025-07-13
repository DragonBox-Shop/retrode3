<?php

include("header.inc.php");

// Updates

html("<p><font color=\"red\">");
switch(getvar("update"))
	{
	case "database":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin update-database"));
		break;
	case "system":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin apt-get-update"));
		break;
	case "poweroff":
		text("Started ..."); flush();
		text(callcmd("sudo /usr/local/bin/retrode-admin poweroff"));
		break;
	}
html("</font></p>");

section(3, "Installation");

// table?
html("<table border=\"1\">");
html("<tr><td>");
text("Device Model:");
html("</td><td>");
text(str_replace(chr(0), '', file_get_contents("/proc/device-tree/model")));
html(" <a href=\"$here?update=poweroff\">Power Off</a> ");
html("</td></tr>");

html("<tr><td>");
text("Current OS Version:");
html("</td><td>");
text(callcmd("fgrep VERSION= /etc/os-release | sed 's/VERSION=//' | sed 's/\"//g'; cat /etc/debian_version"));
// Links auf offizielles Debian Repo
// oder Link auf ein Wiki
html("</td></tr>");

html("<tr><td>");
text("OS Creation Date:");
html("</td><td>");
text(callcmd("date -r /makesd.info '+%Y-%m-%d %H:%M:%S'"));
// Link auf makesd und/oder den Befehl
// created by '<a ref=...>makesd</a>...'
html("</td></tr>");

html("<tr><td>");
text("Last OS Update:");
html("</td><td>");
if(false)
	{ // someone may delete the history.log...
	text(callcmd("awk '/Commandline:/,/End-Date: /{if(/End-Date: /)print $2, $3}' /var/log/apt/history.log | tail -1"));
	}
else
	text(callcmd("date -r /var/lib/apt/lists/download.goldelico.com_letux-debian-rootfs_debian_dists_jessie_main_binary-mipsel_Packages '+%Y-%m-%d %H:%M:%S'"));

// can we somehow check for potential updates without running apt-get update/upgrade?
// Links auf die speziellen Repos (Letux und Retrode) und Source-Code
echo " <a href=\"$here?update=system\">Update OS</a> ";
html("</td></tr>");

html("<tr><td>");
text("Current Kernel Version:");
html("</td><td>");
text(callcmd("uname -a"));
// Links auf kernel Repo
html("</td></tr>");

html("<tr><td>");
text("Last Game Database Update:");
html("</td><td>");
text(callcmd("date -r /usr/local/games/retrode/README.md '+%Y-%m-%d %H:%M:%S'"));
echo " <a href=\"$here?update=database\">Update Game Database</a> ";
// Links auf Game Database: https://github.com/sanni/cartreader/tree/master/sd
html("</td></tr>");

html("<tr><td>");
text("Internet access:");
html("</td><td>");
text("Host PC: ".callcmd("ping -q -c 1 192.168.200 | fgrep PING"));
html("<br>");
text("Debian:  ".callcmd("ping -q -c 1 archive.debian.org | fgrep PING"));
html("<br>");
text("LetuxOS: ".callcmd("ping -q -c 1 www.letux.org | fgrep PING"));
html("<br>");
text("OSCR:    ".callcmd("ping -q -c 1 github.com | fgrep PING"));	// for OSCR Game Database updates
html("</td></tr>");

html("</table>");

// WLAN

$ssid=trim(getvar('ssid'));		// from <input> or connect link
$password=trim(getvar("password"));	// from <input>

if (true)
{
// check if wlan exists (e.g. /sys/class/net/wlan* or search ifconfig -a)
// find interface number through e.g. iwconfig 2>&1 | fgrep 'wlan'

section(3, "WLAN Configuration");

html("<p><font color=\"red\">");
switch(getvar("wlan"))
{
	case "Connect":
		if(!$ssid)
			{
			text("Missing SSID");
			break;
			}
		$cmd="sudo /usr/local/bin/retrode-wlan connect".($password?" -p '$password'":"")." $ssid'";
		text(callcmd($cmd));
		break;
}
html("</font></p>");

$str=callcmd("sudo /usr/local/bin/retrode-wlan status");	// STATUS SSID MAC IP4 IP6
$status=explode(' ', $str."     ");

echo "<table border=\"1\">";
if($status[0] != "connected")
	{
	echo "<tr><td>SSID</td><td><input name=\"ssid\" value=\"$ssid\" width=\"20\"></input>";
	echo " <input type=\"submit\" name=\"wlan\" value=\"Connect\"></input></td></tr>";
// add java script to toggle type between "password" and "text" to unhide the password
	echo "<tr><td>WPA-Key</td><td><input type=\"password\" name=\"password\" value=\"$password\" width=\"20\"></input></td></tr>";
	}
else
	{
	echo "<tr><td>SSID</td><td>"; text($status[1]);
	echo " <input type=\"submit\" name=\"wlan\" value=\"Disconnect\"></input></td></tr>";
	}

echo "<tr><td>IP4 Address</td><td>"; text($status[3]); echo "</td></tr>";
echo "<tr><td>IP6 Address</td><td>"; text($status[4]); echo "</td></tr>";
echo "<tr><td>MAC Address</td><td>"; text($status[2]); echo "</td></tr>";
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

html("... hier sollte der User die Time-Zone und Language dieser Webseiten einstellen können - ausser wir holen d
(zumindest die Language) aus den Browser-Requestdaten. Alternativ könnte das alles in Cookies gesetzt werden.");

// Buttons:
//   Scan
//   Connect

include("footer.inc.php");
?>

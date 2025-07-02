<?php

include("header.inc.php");

// Updates

html("<p><font color=\"red\">");
switch(getvar("update"))
	{
	case "yes":
		$cmd="(
			wget -qO /tmp/cart_reader.zip https://codeload.github.com/sanni/cartreader/zip/refs/heads/master &&
			unzip -q /tmp/cart_reader.zip 'cartreader-master/sd/*' -d /tmp &&
			mv /tmp/cartreader-master/sd/* /usr/local/games/retrode/test &&
			echo Cart database updated. || echo failed.) 2>&1"
			;
		callcmd($cmd);
		break;
	case "system":

// FIXME: E: Could not open lock file /var/lib/apt/lists/lock - open (13: Permission denied) E: Unable to lock directory /var/lib/apt/lists/ E: Could not open lock file /var/lib/dpkg/lock - open (13: Permission denied) E: Unable to lock the administration directory (/var/lib/dpkg/), are you root?

		$cmd="(
			apt-get update && apt-get upgrade &&
			echo System updated. Now rebooting... &&
			reboot || echo failed.) 2>&1;";
		callcmd($cmd);
		break;
	case "poweroff":
		$cmd="(poweroff && echo Will power off now... || echo failed.) 2>&1";
		callcmd($cmd);
		break;
	}
html("</font></p>");

html("<p>");
text("Device Model: ".str_replace(chr(0), '', file_get_contents("/proc/device-tree/model"))); html("</br>");
text("Current Linux Version: "); callcmd("fgrep VERSION= /etc/os-release | sed 's/VERSION=//' | sed 's/\"//g'"); html("</br>");
text("Current Kernel Version: "); callcmd("uname -a"); html("</br>");
html("</p>");

html("<p>");
echo "<a href=\"$here?update=yes\">Update Game Database</a> ";
echo "<a href=\"$here?update=system\">Update Linux</a> ";
echo "<a href=\"$here?update=poweroff\">Power Off</a> ";
html("</p>");

// WLAN

$ssid=trim(getvar('SSID'));		// from <input> or connect link
$password=trim(getvar("PASSWORD"));	// from <input>

if (true)
{
// check if wlan exists (e.g. /sys/class/net/wlan* or search ifconfig -a)
// find interface number through e.g. iwconfig 2>&1 | fgrep 'wlan'

html("<h3>"); text("WLAN Configuration"); html("</h3>");
switch(getvar("wlan"))
{
	case "Connect":
		if(!$ssid)
			{
			text("Missing SSID");
			break;
			}
		$cmd="(/root/wlan-on".($password?" -p '$password'":"")." '$ssid' && echo Successfully connected. || echo failed.) 2>&1";
		callcmd($cmd);
		break;
}
echo "<table border=\"1\">";
echo "<tr><td>SSID</td><td><input name=\"SSID\" value=\"$ssid\" width=\"20\"></input> <input type=\"submit\" name=\"wlan\" value=\"Connect\"></input></td></tr>";

// add java script to toggle type between "password" and "text" to unhide the password

echo "<tr><td>WPA-Key</td><td><input type=\"password\" name=\"PASSWORD\" value=\"$password\" width=\"20\"></input></td></tr>";

// find out information about ifconfig or iwconfig

// associated? // iwconfig -> Access Point: Not-Associated
echo "<tr><td>IP Address</td><td>192.168.178...</td></tr>";	// ifconfig -> inet6 addr: fe80::f2f5:bdff:fe02:313c/64
echo "<tr><td>MAC Address</td><td>xx.xx.xx.xx.xx</td></tr>";	// ifconfig -> HWaddr
echo "<tr><td>Frequency</td><td>2.4 GHz</td></tr>";		// ?
echo "</table>";
}

if (true)
{
// this also needs root permissions!
// see: https://stackoverflow.com/questions/67292960/how-to-run-a-shell-as-root-from-php-apache
html("<h3>"); text("WLAN Networks"); html("</h3>");
callcmd("/root/wlan-scan");

echo "<table border=\"1\">";
echo "<tr><th>SSID</th><th>Band</th><th>dBm</th></tr>";
// Tabelle aus dem Ergebnis bauen und jeweils eine Zeile anlegen:
echo "<tr><td><a href=\"?SSID=TheNetwork\">TheNetwork</a></td><td>2.4GHz</td><td>-50</td></tr>";
echo "<tr><td><a href=\"?SSID=BeamMeUp\">BeamMeUp</a></td><td>2.4GHz</td><td>-50</td></tr>";
echo "</table>";

// Buttons:
//   Scan
//   Connect

}

include("footer.inc.php");
?>

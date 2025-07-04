<?php

include("header.inc.php");

// Updates

html("<p><font color=\"red\">");
switch(getvar("update"))
	{
	case "database":
		text(callcmd("sudo /usr/local/bin/retrode-admin update-database"));
		break;
	case "system":
		text(callcmd("sudo /usr/local/bin/retrode-admin apt-get-update"));
		break;
	case "poweroff":
		text(callcmd("sudo /usr/local/bin/retrode-admin poweroff"));
		break;
	}
html("</font></p>");

// table?
html("<p>");
text("Device Model: ".str_replace(chr(0), '', file_get_contents("/proc/device-tree/model"))); html("</br>");
text("Current Linux Version: "); text(callcmd("fgrep VERSION= /etc/os-release | sed 's/VERSION=//' | sed 's/\"//g'")); html("</br>");
text("Current Kernel Version: "); text(callcmd("uname -a")); html("</br>");
html("</p>");

html("<p>");
echo "<a href=\"$here?update=database\">Update Game Database</a> ";
echo "<a href=\"$here?update=system\">Update Linux</a> ";
echo "<a href=\"$here?update=poweroff\">Power Off</a> ";
html("</p>");

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

if (true)
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

// Buttons:
//   Scan
//   Connect

}

include("footer.inc.php");
?>

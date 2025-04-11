<?php

include("header.inc.php");

if(isset($_GET['update']))
{
	switch($_GET['update'])
		{
		case "yes":
			system("(wget -qO /tmp/cart_reader.zip https://codeload.github.com/sanni/cartreader/zip/refs/heads/master && unzip -q /tmp/cart_reader.zip 'cartreader-master/sd/*' -d /tmp && mv /tmp/cartreader-master/sd/* /usr/local/games/retrode/test && echo Cart database updated. || echo failed.) 2>&1");
			break;
		case "system":

// FIXME: E: Could not open lock file /var/lib/apt/lists/lock - open (13: Permission denied) E: Unable to lock directory /var/lib/apt/lists/ E: Could not open lock file /var/lib/dpkg/lock - open (13: Permission denied) E: Unable to lock the administration directory (/var/lib/dpkg/), are you root?

			system("(apt-get update && apt-get upgrade && echo System updated. Now rebooting... && reboot || echo failed.) 2>&1");
			break;
		case "poweroff":

// FIXME: poweroff: must run as superuser.

			system("(poweroff && echo Will power off now... || echo failed.) 2>&1");
			break;
		}
}

echo "<p>";
echo "<a href=\"$here?update=yes\">Update Game Database</a> ";
echo "<a href=\"$here?update=system\">Update Linux</a> ";
echo "<a href=\"$here?update=poweroff\">Power Off</a> ";
echo "</p>";

echo "allow to configure WLAN here";

include("footer.inc.php");
?>

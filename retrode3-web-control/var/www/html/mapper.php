<?php

include("header.inc.php");

?>
<h3>Raw Access</h3>
<p>
<a href="?dump=headers">Dump ROM Headers</a>
</p>
<?php
$dump=getvar("dump");
switch($dump)
	{
	case "headers":
		html("<pre>");
		text(callcmd("sudo /usr/local/bin/retrode-dump $dump"));
		html("</pre>");
		break;
	}
?>

<h3>RAM Tools</h3>
<p>
<a href="?dump=ram">Dump RAM</a>
</p>
<?php
$dump=getvar("dump");
switch($dump)
	{
	case "ram":
		html("<pre>");
		text(callcmd("sudo /usr/local/bin/retrode-dump $dump"));
		html("</pre>");
		break;
	}
?>

<h2>Experimental or not implemented</h2>
<h3>Cart Doctor</h3>
Add tools to detect card contents. Like calling ucon64.

<h3>Cart Flasher</h3>
Flash Carts with EEPROM.

<h3>Select Mapper</h3>
Manually select mapper: <input name="mapper" type="text" width="20">
<p>
<input type="checkbox">Checkbox</input>
<p>
<input type="radio">Radio</input>
<p>


<?php
include("footer.inc.php");
?>

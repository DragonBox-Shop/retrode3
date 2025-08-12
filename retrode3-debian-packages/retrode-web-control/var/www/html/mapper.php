<?php

include("header.inc.php");

?>
<h3>Select Mapper</h3>
Manually select mapper: <input name="mapper" type="text" width="20">
<p>
<input type="checkbox">Checkbox</input>
<p>
<input type="radio">Radio</input>
<p>

<h3>Raw Read</h3>
<p>
<a href="?action=headers">Dump Headers</a>
</p>
<?php
$action=getvar("action");
if($action)
	{
	html("<pre>");
	text(callcmd("sudo /usr/local/bin/retrode-dump $action"));
	html("</pre>");
	}
?>

<h3>Cart Doctor</h3>
Add tools to detect card contents. Like calling ucon64.

<h3>RAM Tools</h3>
Add tools to read/write RAM content.

<h3>Cart Flasher</h3>
Flash Carts with EEPROM.

<?php
include("footer.inc.php");
?>

<?php

include("header.inc.php");

?>
<h3>Cart Doctor</h3>
Add tools to detect card contents
<h3>Select Mapper</h3>
Manually select mapper: <input name="mapper" type="text" width="20">
<p>
<input type="checkbox">Checkbox</input>
<p>
<input type="radio">Radio</input>
<p>

<h3>Raw Read</h3>
<p>
<a href="?raw=slot0">Slot 0</a>
<a href="?raw=slot1">Slot 1</a>
<a href="?raw=slot2">Slot 2</a>
</p>
<?php
$slot=getvar("raw");
if($slot)
	{
	$slot=str_replace("/..", "", "/dev/".$slot);
	callcmd("(xxd $slot | head -32) 2>&1");
	}
?>

<h3>Cart Flasher</h3>
Flash Carts with EEPROM.

<?php
include("footer.inc.php");
?>

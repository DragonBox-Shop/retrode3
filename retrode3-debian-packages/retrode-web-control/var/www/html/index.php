<?php

include("header.inc.php");

if($slot=getvar('slot'))
	{ // read out cart
	$slot="/dev/slot-".$slot;
	$slot=str_replace("/..", "", $slot);
	echo "<p>Reading ".getvar('name')."</p>";
	echo "<p>Please wait...";
	flush();
	text(callcmd("sudo /usr/local/bin/retrode-read $slot"));
	echo " ...done.</p>";
	flush();
	// needs some logic and scanning to find out what the file name is...
	$name=getvar('slot');
	weblink("Show File", "files.html?dir=$name");
	}

?>
<p>
Alternative methods of access (depends on host OS):
</ul>
<li>serial console login on USB (works like an FTDI adapter)</li>
<li>ssh root@<?php echo $_SERVER['SERVER_ADDR']; ?></li>
<li><a href="smb://<?php echo $_SERVER['SERVER_ADDR']; ?>/retrode">mount smb <?php echo $_SERVER['SERVER_ADDR']; ?>/retrode</a></li>
</ul>
</p>
<?php
section(2, "Slot Status");

function show_status_as_table()
{
	global $here;
	$image="retrode";
	echo "<table border=\"1\">";
	foreach(array("md" => "MegaDrive", "snes" => "SNES", "nes" => "NES") as $slot => $name)
		{
		echo "<tr>";
		echo "<td>".htmlentities($name)."</td>";
		$status=trim(file_get_contents("/sys/class/retrode3/slot-$slot/sense"));
		echo "<td>";
		if($status == "active")
			{ // there is a Cart inserted
			$str=callcmd("sudo /usr/local/bin/retrode-info /dev/slot-$slot", "r");
			if(!$str)
				text("unidentified");
			else
				{
				text($str);
				html(" ");
				html("<a href=");
				html("\"$here?slot=".rawurlencode($slot)."&name=".rawurlencode("MD/ROM/$str")."\"");
				html(">");
				text("Extract");
				html("</a>");
				}
			$image.="+$slot";
			}
		else
			text("empty");
		echo "</td>";
// fails:	system("/root/copyrom /dev/slot$SLOT /tmp/slot.bin; wc -c </tmp/slot.bin");
		// besser: ein slot-info.sh aufrufen das den retrode-Befehl benutzt
		echo "</tr>";
		}

	foreach(array("left", "right") as $name)
		{
		echo "<tr>";
		echo "<td>".htmlentities("$name Controller")."</td>";
		echo "<td>";
		if(file_exists("/dev/input/$name"))
			{
			echo "<font color=\"green\">CONNECTED</font>";
			$image.="+$name";
/* here we could loop over all KEYs
 * and run
 *    evtest --query /dev/input/right EV_KEY KEY_A && echo no || echo yes
    Event code 19 (KEY_R)
    Event code 21 (KEY_Y)
    Event code 22 (KEY_U)
    Event code 30 (KEY_A)
    Event code 31 (KEY_S)
    Event code 32 (KEY_D)
    Event code 38 (KEY_L)
    Event code 44 (KEY_Z)
    Event code 45 (KEY_X)
    Event code 46 (KEY_C)
    Event code 48 (KEY_B)
    Event code 50 (KEY_M)

	$keys="ABCDLRSUXYZ";
	foreach($key in $keys)
		$cmd="evtest --query /dev/input/$name EV_KEY KEY_$key && echo no || echo $key"
 */
			}
		else
			echo "not connected";
		echo "</td>";
		echo "</tr>";
	}

	echo "<tr>";
	echo "<td>SD Card partitions</td>";
	echo "<td>";
	$file=file("/proc/partitions");
	foreach($file as $str)
		{
		//echo $str;
		if (preg_match ('/(\d+)\s+(\d+)\s+(\d+)\s+(mmcblk.p.+)/', $str, $m))
			echo sprintf("%s %.1f GB", $m[4], $m[3]/(1024.0*1024))."<br>";	// partition name and size
//		else echo "not: ".$str."<br>";
		// could try to extract partition names, types etc.
		}
	echo "</td>";
	echo "</tr>";

	html("</table>");

	return $image;
}

function show_status_as_photo($status)
{
	// FIXME: use ImageMagick to compose an image from components
	html("<img src=\"$status.jpg\"></img>");
}

html("<table width=\"100%\">");
html("<td><td>");
$status=show_status_as_table();
html("</td><td>");
show_status_as_photo($status);
html("</td></tr>");
html("</table>");

?>
<h2>Button Status</h2>
<p>
<?php

echo "here we could read the button status of /dev/input/event0 if we have a use for it...";

?>

<?php
include("footer.inc.php");
?>

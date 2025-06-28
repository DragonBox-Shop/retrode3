<?php

include("header.inc.php");

?>
<p>
This is just a demo of what is possible with a HTML GUI.
Alternative methods of access (depends on host OS):
</ul>
<li>serial console login on USB (works like an FTDI adapter)</li>
<li>ssh root@192.168.0.202</li>
<li>mount smb <a href="smb://192.168.0.202/media">192.168.0.202/media</a></li>
</ul>
</p>
<h2>Slot Status</h2>
<?php

echo "<table border=\"1\">";
// this is not universal in the sense that there is a different assignment between 2.9.3 and 2.9.4
foreach(array(0 => "MegaDrive", 1 => "SNES", 2 => "NES") as $SLOT => $NAME)
	{
	echo "<tr>";
	echo "<td>".htmlentities($NAME)."</td>";
	$status=trim(file_get_contents("/sys/class/retrode3/slot$SLOT/sense"));
	echo "<td>";
	if($status == "active")
		{ // there is a Cart inserted
		$file=popen("sh -vc '/usr/local/bin/retrode-info /dev/slot$SLOT'", "r");
		$str=stream_get_contents($file);
		fclose($file);
		if(!$str)
			$str="unidentified";
		echo "<a href=\"$here?slot=$SLOT&name=$NAME\">".htmlentities($str)."</a>";
		}
	else
		echo "empty";
	echo "</td>";
// fails:	system("/root/copyrom /dev/slot$SLOT /tmp/slot.bin; wc -c </tmp/slot.bin");
	// besser: ein slot-info.sh aufrufen das den retrode-Befehl benutzt
	echo "</tr>";
	}

if(isset($_GET['slot']))
	{ // read out cart
	$slot="/dev/slot".$_GET['slot'];	// check for tampering with slot name e.g. 0/../..
	echo "<p>Reading ".$_GET['name']."</p>";
	echo "<p>Please wait...";
	flush();
	fclose(popen("/usr/local/bin/retrode-read $slot", "r"));
	echo " ...done.</p>";
	flush();
	}

foreach(array("left", "right") as $NAME)
{
	echo "<tr>";
	echo "<td>".htmlentities("$NAME Controller")."</td>";
	echo "<td>";
	if(file_exists("/dev/input/$NAME"))
		echo "<font color=\"green\">CONNECTED</font>";
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
		echo $m[4]." (".ceil($m[3]/(1024*1024))." MB)<br>";	// partition name and size
//	else echo "not: ".$str."<br>";
	// could try to extract partition names, types etc.
	}
echo "</td>";
echo "</tr>";

echo "</table>";

?>
<h2>Button Status</h2>
<p>
<?php

echo "here we could read the button status of /dev/input/event0 if we have a use for it...";

?>

<?php
include("footer.inc.php");
?>

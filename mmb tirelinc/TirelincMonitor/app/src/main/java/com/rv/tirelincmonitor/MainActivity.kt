package com.rv.tirelincmonitor

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity

/**
 * Minimal launcher activity — lets you manually trigger the beep test
 * without rebooting the device. Tap "Test Beep" to verify the service works.
 */
class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<TextView>(R.id.tvStatus).text =
            "Tirelinc Monitor\nP2 - Startup Beep Test\n\nApp will auto-start on device boot."

        findViewById<Button>(R.id.btnTestBeep).setOnClickListener {
            val intent = Intent(this, BeepService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(intent)
            } else {
                startService(intent)
            }
        }
    }
}

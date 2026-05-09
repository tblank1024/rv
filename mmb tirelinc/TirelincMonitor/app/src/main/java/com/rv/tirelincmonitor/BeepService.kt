package com.rv.tirelincmonitor

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper

/**
 * P2 test service: plays a short beep once per second for 30 seconds at startup.
 * Runs as a foreground service so Android doesn't kill it in the background.
 *
 * Later phases will replace this with tire pressure monitoring logic.
 */
class BeepService : Service() {

    private val handler = Handler(Looper.getMainLooper())
    private var beepCount = 0
    private var toneGenerator: ToneGenerator? = null

    companion object {
        private const val CHANNEL_ID = "tirelinc_channel"
        private const val NOTIFICATION_ID = 1
        const val MAX_BEEPS = 30           // 30 beeps = 30 seconds
        const val BEEP_DURATION_MS = 100   // short beep: 0.1 sec
        const val BEEP_INTERVAL_MS = 1000L // one beep per second
    }

    private val beepRunnable = object : Runnable {
        override fun run() {
            if (beepCount < MAX_BEEPS) {
                toneGenerator?.startTone(ToneGenerator.TONE_PROP_BEEP, BEEP_DURATION_MS)
                beepCount++
                handler.postDelayed(this, BEEP_INTERVAL_MS)
            } else {
                stopSelf()
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        // MMB audio routes through the car amplifier (van speakers).
        // STREAM_ALARM is the correct stream for safety alerts.
        toneGenerator = tryCreateToneGenerator(
            AudioManager.STREAM_ALARM,
            AudioManager.STREAM_MUSIC
        )
        createNotificationChannel()
    }

    private fun tryCreateToneGenerator(vararg streams: Int): ToneGenerator? {
        for (stream in streams) {
            try {
                return ToneGenerator(stream, ToneGenerator.MAX_VOLUME)
            } catch (e: Exception) {
                // stream not available, try next
            }
        }
        return null
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground(NOTIFICATION_ID, buildNotification())
        beepCount = 0
        handler.post(beepRunnable)
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(beepRunnable)
        toneGenerator?.release()
        toneGenerator = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Tirelinc Alerts",
                NotificationManager.IMPORTANCE_LOW
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(): Notification {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Tirelinc Monitor")
                .setContentText("Startup check active...")
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setOngoing(true)
                .build()
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
                .setContentTitle("Tirelinc Monitor")
                .setContentText("Startup check active...")
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setOngoing(true)
                .build()
        }
    }
}

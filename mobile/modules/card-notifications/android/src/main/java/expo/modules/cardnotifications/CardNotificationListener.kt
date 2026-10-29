package expo.modules.cardnotifications

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * 카드사 앱 결제 알림만 골라 서버로 보낸다.
 * 허용 목록에 없는 앱의 알림은 여기서 버려 앱 밖으로 나가지 않는다.
 */
class CardNotificationListener : NotificationListenerService() {
  override fun onNotificationPosted(sbn: StatusBarNotification) {
    val store = ChargeUploader.store(this)
    if (sbn.packageName !in store.cardPackages) return

    val extras = sbn.notification.extras
    val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
    val text = (extras.getCharSequence(Notification.EXTRA_BIG_TEXT)
      ?: extras.getCharSequence(Notification.EXTRA_TEXT))?.toString().orEmpty()
    if (title.isBlank() && text.isBlank()) return

    ChargeUploader.enqueue(this, id = "${sbn.key}:${sbn.postTime}", postedAt = sbn.postTime, title = title, text = text)
  }
}

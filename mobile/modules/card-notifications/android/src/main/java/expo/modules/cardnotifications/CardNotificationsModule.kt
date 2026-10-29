package expo.modules.cardnotifications

import android.content.Intent
import android.provider.Settings
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

class CardNotificationsModule : Module() {
  private val context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  override fun definition() = ModuleDefinition {
    Name("CardNotifications")

    Events("onCharge")

    OnCreate {
      ChargeUploader.onSaved = { body -> sendEvent("onCharge", mapOf("body" to body)) }
    }

    OnDestroy {
      ChargeUploader.onSaved = null
    }

    /** 설정 > 알림 접근 허용에서 이 앱이 켜져 있는지 */
    Function("isPermissionGranted") {
      val enabled = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners").orEmpty()
      enabled.contains(context.packageName)
    }

    Function("openPermissionSettings") {
      val intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
    }

    Function("configure") { serverUrl: String, token: String, cardPackages: List<String> ->
      ChargeUploader.store(context).configure(serverUrl, token, cardPackages)
      ChargeUploader.flush(context)
    }

    Function("getConfig") {
      val store = ChargeUploader.store(context)
      mapOf("serverUrl" to store.serverUrl, "token" to store.token)
    }

    Function("flush") {
      ChargeUploader.flush(context)
    }

    Function("pendingCount") {
      ChargeUploader.pendingCount(context)
    }
  }
}

package expo.modules.cardnotifications

import android.content.Context
import android.content.SharedPreferences
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * 결제 알림 전송 큐. 서버에 못 보내면(오프라인·서버 꺼짐) 저장해 두고 다음 알림이나 앱 실행 때 다시 보낸다.
 * 앱이 꺼져 있어도 알림 수집 서비스에서 바로 전송한다.
 */
object ChargeUploader {
  private const val PREFS = "card_notifications"
  private val executor = Executors.newSingleThreadExecutor()

  /** 앱이 떠 있으면 서버가 저장한 결제를 JS 로 알린다. 응답 JSON 문자열을 넘긴다. */
  @Volatile var onSaved: ((String) -> Unit)? = null

  class Store(private val prefs: SharedPreferences) {
    val serverUrl: String get() = prefs.getString("server_url", "").orEmpty().trimEnd('/')
    val token: String get() = prefs.getString("token", "").orEmpty()
    val cardPackages: Set<String> get() = prefs.getStringSet("card_packages", emptySet()).orEmpty()
    var queue: JSONArray
      get() = JSONArray(prefs.getString("queue", "[]"))
      set(value) = prefs.edit().putString("queue", value.toString()).apply()

    fun configure(serverUrl: String, token: String, cardPackages: List<String>) {
      prefs.edit()
        .putString("server_url", serverUrl)
        .putString("token", token)
        .putStringSet("card_packages", cardPackages.toSet())
        .apply()
    }
  }

  fun store(context: Context) = Store(context.getSharedPreferences(PREFS, Context.MODE_PRIVATE))

  fun enqueue(context: Context, id: String, postedAt: Long, title: String, text: String) {
    val item = JSONObject().put("id", id).put("posted_at", postedAt).put("title", title).put("text", text)
    executor.execute {
      val store = store(context)
      store.queue = store.queue.put(item)
      drain(store)
    }
  }

  fun flush(context: Context) = executor.execute { drain(store(context)) }

  fun pendingCount(context: Context): Int = store(context).queue.length()

  private fun drain(store: Store) {
    if (store.serverUrl.isEmpty() || store.token.isEmpty()) return
    val queue = store.queue
    val remaining = JSONArray()
    for (i in 0 until queue.length()) {
      val item = queue.getJSONObject(i)
      val keep = try {
        val (status, body) = post("${store.serverUrl}/api/notifications/", store.token, item)
        if (status == 201) onSaved?.invoke(body)
        // 서버 오류·토큰 오류는 고쳐진 뒤 다시 보낸다. 그 외(중복·결제 아님·형식 오류)는 버린다.
        status >= 500 || status == 401 || status == 403
      } catch (e: IOException) {
        true
      }
      if (keep) remaining.put(item)
    }
    store.queue = remaining
  }

  private fun post(url: String, token: String, item: JSONObject): Pair<Int, String> {
    val conn = URL(url).openConnection() as HttpURLConnection
    try {
      conn.requestMethod = "POST"
      conn.connectTimeout = 10_000
      conn.readTimeout = 30_000
      conn.doOutput = true
      conn.setRequestProperty("Content-Type", "application/json")
      conn.setRequestProperty("Authorization", "Bearer $token")
      conn.outputStream.use { it.write(item.toString().toByteArray()) }
      val status = conn.responseCode
      val stream = if (status < 400) conn.inputStream else conn.errorStream
      return status to (stream?.bufferedReader()?.use { it.readText() } ?: "")
    } finally {
      conn.disconnect()
    }
  }
}

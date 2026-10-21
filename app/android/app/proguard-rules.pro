# shared_preferences_android 2.5 calls its Kotlin API from Dart over JNI,
# looking classes and method signatures up by name. R8 sees no Java callers,
# so it strips or renames them and release builds crash on start. Keep every
# class those lookups name, including the Kotlin types in the signatures.
-keep class io.flutter.plugins.sharedpreferences.** { *; }
-keep class com.github.dart_lang.jni.** { *; }
-keep class kotlin.coroutines.Continuation { *; }
-keep class kotlin.coroutines.intrinsics.** { *; }
-keep class kotlin.Result { *; }
-keep class kotlin.Result$Failure { *; }
-keep class kotlin.Unit { *; }
-keep class kotlin.jvm.internal.DefaultConstructorMarker { *; }

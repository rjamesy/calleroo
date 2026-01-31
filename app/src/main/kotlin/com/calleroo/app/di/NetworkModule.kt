package com.calleroo.app.di

import com.calleroo.app.BuildConfig
import com.calleroo.app.network.ConversationApi
import com.calleroo.app.network.SchedulerApi
import javax.inject.Qualifier
import com.jakewharton.retrofit2.converter.kotlinx.serialization.asConverterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = true
    }

    @Provides
    @Singleton
    fun provideOkHttpClient(): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)

        if (BuildConfig.DEBUG) {
            val loggingInterceptor = HttpLoggingInterceptor().apply {
                level = HttpLoggingInterceptor.Level.BODY
            }
            builder.addInterceptor(loggingInterceptor)
        }

        return builder.build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(okHttpClient: OkHttpClient): Retrofit {
        val contentType = "application/json".toMediaType()
        return Retrofit.Builder()
            .baseUrl(BuildConfig.BACKEND_BASE_URL)
            .client(okHttpClient)
            .addConverterFactory(json.asConverterFactory(contentType))
            .build()
    }

    @Provides
    @Singleton
    fun provideConversationApi(retrofit: Retrofit): ConversationApi {
        return retrofit.create(ConversationApi::class.java)
    }

    /**
     * Provide Retrofit for Scheduler service (separate from main backend).
     * Returns null if SCHEDULER_BASE_URL is empty or invalid (feature disabled).
     */
    @Provides
    @Singleton
    @SchedulerRetrofit
    fun provideSchedulerRetrofit(okHttpClient: OkHttpClient): Retrofit? {
        val schedulerUrl = BuildConfig.SCHEDULER_BASE_URL.trim()

        // Feature disabled if empty
        if (schedulerUrl.isBlank()) {
            return null
        }

        // Validate URL has valid scheme (http or https)
        if (!schedulerUrl.startsWith("http://") && !schedulerUrl.startsWith("https://")) {
            // Invalid URL, treat as disabled to avoid crashes
            return null
        }

        // Ensure URL has trailing slash (required by Retrofit)
        val normalizedUrl = if (schedulerUrl.endsWith("/")) schedulerUrl else "$schedulerUrl/"

        return try {
            val contentType = "application/json".toMediaType()
            Retrofit.Builder()
                .baseUrl(normalizedUrl)
                .client(okHttpClient)
                .addConverterFactory(json.asConverterFactory(contentType))
                .build()
        } catch (e: Exception) {
            // If Retrofit fails to build (e.g., malformed URL), treat as disabled
            null
        }
    }

    /**
     * Provide SchedulerApi if scheduler URL is configured.
     * Returns null if scheduler is not available.
     */
    @Provides
    @Singleton
    fun provideSchedulerApi(@SchedulerRetrofit retrofit: Retrofit?): SchedulerApi? {
        return retrofit?.create(SchedulerApi::class.java)
    }
}

/**
 * Qualifier annotation for Scheduler-specific Retrofit instance.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class SchedulerRetrofit

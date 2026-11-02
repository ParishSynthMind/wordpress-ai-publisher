<?php
/**
 * Plugin Name: Local test only - forced 429
 * Description: For integration tests. Only active when WP_ENVIRONMENT_TYPE is "local".
 *              `wp option update aipub_force_429 N` makes the next N REST requests answer
 *              429 Too Many Requests with Retry-After: 1. Do not deploy to a real site.
 */

if (!function_exists('wp_get_environment_type') || wp_get_environment_type() !== 'local') {
    return;
}

add_filter('rest_pre_dispatch', function ($result, $server, $request) {
    $remaining = (int) get_option('aipub_force_429', 0);
    if ($remaining <= 0) {
        return $result;
    }
    update_option('aipub_force_429', $remaining - 1, false);
    $response = new WP_REST_Response(['code' => 'rate_limited', 'message' => 'Too many requests (forced by local test plugin).'], 429);
    $response->header('Retry-After', '1');
    return $response;
}, 1, 3);

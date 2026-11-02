<?php
/**
 * Plugin Name: AI Publisher meta description
 * Description: Lets the REST API write a meta description for posts and prints it in the page head.
 *              Copy to wp-content/mu-plugins/ on the client site. Not needed if Yoast or Rank Math
 *              handles meta descriptions (see README).
 */

add_action('init', function () {
    register_post_meta('post', 'ai_meta_description', [
        'type'              => 'string',
        'single'            => true,
        'show_in_rest'      => true,
        'sanitize_callback' => 'sanitize_text_field',
        'auth_callback'     => function () {
            return current_user_can('edit_posts');
        },
    ]);
});

add_action('wp_head', function () {
    if (!is_singular('post')) {
        return;
    }
    $description = get_post_meta(get_queried_object_id(), 'ai_meta_description', true);
    if ($description) {
        printf("<meta name=\"description\" content=\"%s\" />\n", esc_attr($description));
    }
}, 1);

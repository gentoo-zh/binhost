add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header X-Frame-Options "DENY" always;
add_header Content-Security-Policy "default-src 'none'; sandbox" always;
add_header Alt-Svc 'h3=":443"; ma=86400' always;
add_header X-Robots-Tag "noindex" always;

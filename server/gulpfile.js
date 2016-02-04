
var gulp = require('gulp');
var browserify = require('browserify');
var reactify = require('reactify');
var source = require('vinyl-source-stream');
var buffer = require('vinyl-buffer');
var watchify = require('watchify');
var uglify = require('gulp-uglifyjs');
var sourcemaps = require('gulp-sourcemaps');
var gutil = require('gulp-util');

var _ = require('underscore');

function bundle(watch)
{
    var bundler;
    var input = './client/index.js';

    var args = _.extend({}, watchify.args, {debug: true});

    if (watch) {
        bundler = watchify(browserify(input, args));
    } else {
        bundler = browserify(input, {debug: true});
    }
    bundler.transform('reactify');
    
    function bundleProper()
    {
        return bundler.bundle()
            .pipe(source('bundle.js'))
            .pipe(buffer())
            .pipe(sourcemaps.init())
            //.pipe(uglify())
            .on('error', gutil.log)
            .pipe(sourcemaps.write('./'))
            .pipe(gulp.dest('./client'));
    }

    var b = bundleProper();

    if (watch) {
        bundler.on('update', bundleProper);
        bundler.on('error', function(e) {
            console.log(e.message);
            this.end();
        });
    }

    return b;
}

gulp.task('browserify', function() {
    bundle(false);
});

gulp.task('watchify', function() {
    bundle(true);
});

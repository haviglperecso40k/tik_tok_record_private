import signal
import sys
import os
import multiprocessing

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def record_user(
    user, url, room_id, mode, interval, proxy, output, duration,
    use_telegram, cookies, watchlist_file, shard_index, shard_count,
    max_workers, jitter_seconds, backoff_minutes
):
    from core.tiktok_recorder import TikTokRecorder
    from utils.logger_manager import logger
    try:
        TikTokRecorder(
            url=url,
            user=user,
            room_id=room_id,
            mode=mode,
            automatic_interval=interval,
            cookies=cookies,
            proxy=proxy,
            output=output,
            duration=duration,
            use_telegram=use_telegram,
            watchlist_file=watchlist_file,
            shard_index=shard_index,
            shard_count=shard_count,
            max_workers=max_workers,
            jitter_seconds=jitter_seconds,
            backoff_minutes=backoff_minutes,
        ).run()
    except Exception as e:
        logger.error(f"{e}")


def run_recordings(args, mode, cookies):
    if isinstance(args.user, list):
        processes = []
        for user in args.user:
            p = multiprocessing.Process(
                target=record_user,
                args=(
                    user,
                    args.url,
                    args.room_id,
                    mode,
                    args.automatic_interval,
                    args.proxy,
                    args.output,
                    args.duration,
                    args.telegram,
                    cookies,
                    args.watchlist_file,
                    args.shard_index,
                    args.shard_count,
                    args.max_workers,
                    args.jitter_seconds,
                    args.backoff_minutes
                )
            )
            p.start()
            processes.append(p)
        for p in processes:
            p.join()
    else:
        record_user(
            args.user,
            args.url,
            args.room_id,
            mode,
            args.automatic_interval,
            args.proxy,
            args.output,
            args.duration,
            args.telegram,
            cookies,
            args.watchlist_file,
            args.shard_index,
            args.shard_count,
            args.max_workers,
            args.jitter_seconds,
            args.backoff_minutes
        )


def main():
    from utils.args_handler import validate_and_parse_args
    from utils.utils import read_cookies
    from utils.logger_manager import logger
    from utils.custom_exceptions import TikTokRecorderError
    from check_updates import check_updates

    try:
        # validate and parse command line arguments
        args, mode = validate_and_parse_args()

        # check for updates
        if args.update_check is True:
            logger.info("Checking for updates...\n")
            if check_updates():
                exit()
        else:
            logger.info("Skipped update check\n")

        # read cookies from the config file
        cookies = read_cookies()

        # run the recordings based on the parsed arguments
        run_recordings(args, mode, cookies)

    except TikTokRecorderError as ex:
        logger.error(f"Application Error: {ex}")

    except Exception as ex:
        logger.critical(f"Generic Error: {ex}", exc_info=True)


if __name__ == "__main__":
    # print the banner
    from utils.utils import banner
    banner()

    # check and install dependencies
    from utils.dependencies import check_and_install_dependencies
    check_and_install_dependencies()

    # set up signal handling for graceful shutdown
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    multiprocessing.freeze_support()

    # run
    main()

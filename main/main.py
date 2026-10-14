# Entry point for the overlay manager and the existing profile-sync script.
import sys

if __name__ == "__main__":
    if '--racechat-sync' in sys.argv:
        try:
            from racechat_profile_sync import main
            sys.exit(main(dry_run='--dry-run' in sys.argv))
        except Exception:
            # Never print exception data that could contain account settings.
            sys.exit(1)
    else:
        import manager
        manager.run()

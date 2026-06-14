/// Shape, spacing and elevation tokens for Calm Intelligence.
///
/// Spacing follows a 4px base unit. Cards and surfaces have NO elevation —
/// depth comes from background-colour steps and borders. Elevation (8) is used
/// only on bottom sheets and modal dialogs.
class AppDimens {
  AppDimens._();

  // Border radii
  static const double cardRadius = 12;
  static const double inputRadius = 8;
  static const double pillRadius = 999;
  static const double modalRadius = 16;

  // Spacing scale (multiples of 4)
  static const double space1 = 4;
  static const double space2 = 8;
  static const double space3 = 12;
  static const double space4 = 16;
  static const double space5 = 20;
  static const double space6 = 24;
  static const double space8 = 32;
  static const double space10 = 40;
  static const double space12 = 48;

  // Elevation — only menus/sheets/dialogs.
  static const double sheetElevation = 8;
}

# Préparer le Raspberry Pi (matériel, OS, pilotes)

Tout ce qu'il faut faire **avant** d'installer le client satellite
lui-même (voir [README.md](README.md)) : choisir le matériel, installer
Raspberry Pi OS, puis les pilotes du ReSpeaker 2-Mics Pi HAT.

## Matériel

- **Raspberry Pi 4** (2 Go de RAM suffisent — ce client n'a pas besoin de
  GPU ni de beaucoup de RAM, tout le traitement lourd reste sur le PC).
- **ReSpeaker 2-Mics Pi HAT v2.0** (Seeed Studio) — vérifie que c'est bien
  la v2 (voir [comment distinguer v1/v2](https://wiki.seeedstudio.com/how-to-distinguish-respeaker_2-mics_pi_hat-hardware-revisions/)
  si le doute persiste) : la procédure ci-dessous est spécifique à la v2.
- **Carte microSD** (16 Go minimum, class 10/UHS recommandée).
- **Alimentation USB-C 5V/3A** (officielle Raspberry Pi ou équivalente —
  une alimentation sous-dimensionnée cause des plantages aléatoires).
- **Haut-parleur** compatible avec la sortie du HAT (jack 3.5mm ou JST2.0).
- Un boîtier compatible HAT empilé est optionnel.

## Installer Raspberry Pi OS 64 bits

Utilise **Raspberry Pi Imager** (<https://www.raspberrypi.com/software/>),
depuis n'importe quel PC (Windows/macOS/Linux) :

1. Branche la carte microSD sur ce PC (adaptateur si besoin).
2. Ouvre Raspberry Pi Imager.
3. **Device** : choisis "Raspberry Pi 4".
4. **Operating System** : choisis **"Raspberry Pi OS (64-bit)"** (pas la
   version 32 bits : `onnxruntime` n'existe pas pour elle).
5. **Storage** : sélectionne ta carte microSD (vérifie bien la taille
   affichée pour ne pas écraser un autre disque par erreur).
6. Un écran de pré-configuration s'ouvre automatiquement avant l'écriture —
   remplis-le pour un premier démarrage sans écran/clavier branchés
   (utile si le Pi finit près d'une prise plutôt que sur ton bureau) :
   - **Hostname** : ex. `jarvis-satellite` (facilite la connexion ensuite :
     `ssh utilisateur@jarvis-satellite.local`).
   - **User** : ton nom d'utilisateur + mot de passe.
   - **Wi-Fi** : SSID + mot de passe de ton réseau (ou Ethernet, pas besoin
     de le configurer ici).
   - **Localisation** : fuseau horaire, disposition clavier.
   - **Remote Access (SSH)** : active-le — c'est ce qui permet de continuer
     l'installation à distance, sans écran ni clavier sur le Pi.
   - (Les versions plus anciennes de Raspberry Pi Imager affichent ces mêmes
     réglages derrière une icône ⚙️ engrenage plutôt qu'un assistant.)
7. Lance l'écriture, attends la fin, insère la carte dans le Pi et démarre-le.

## Se connecter au Pi

Depuis un autre appareil du même réseau (PC, autre Pi...) :

```bash
ssh utilisateur@jarvis-satellite.local
```

(remplace `utilisateur` et `jarvis-satellite` par ce que tu as mis dans
Imager). Si `.local` ne résout pas (mDNS peu fiable selon les réseaux),
trouve l'IP du Pi via ton routeur et utilise-la directement
(`ssh utilisateur@192.168.1.xxx`).

## Installer les pilotes du ReSpeaker 2-Mics Pi HAT v2.0

Éteins le Pi (`sudo shutdown now`), **fixe le HAT sur les broches GPIO**
(bien aligné, jamais décalé d'une rangée), puis rallume-le et reconnecte-toi
en SSH. Procédure officielle
([wiki Seeed Studio, page v2.0](https://wiki.seeedstudio.com/respeaker_2_mics_pi_hat_raspberry_v2/)) :

```bash
# Outils nécessaires pour compiler l'overlay de device tree (souvent déjà
# présents sur Raspberry Pi OS, installés ici par précaution).
sudo apt update
sudo apt install -y git device-tree-compiler build-essential

git clone https://github.com/Seeed-Studio/seeed-linux-dtoverlays.git
cd seeed-linux-dtoverlays/
make overlays/rpi/respeaker-2mic-v2_0-overlay.dtbo
sudo cp overlays/rpi/respeaker-2mic-v2_0-overlay.dtbo /boot/firmware/overlays/respeaker-2mic-v2_0.dtbo
echo "dtoverlay=respeaker-2mic-v2_0" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

**`/boot/firmware/config.txt`** (pas `/boot/config.txt`) : le chemin sur
Raspberry Pi OS Bookworm et Trixie.

### Vérifier que le HAT est détecté

Une fois reconnecté en SSH après le redémarrage :

```bash
aplay -l
arecord -l
```

Tu dois voir une carte son nommée `seeed2micvoicec` dans les deux listes
(ex: `card 2: seeed2micvoicec`). Note bien son numéro (`X` ci-dessous) — il
peut différer du tien.

### Tester le micro et le haut-parleur

```bash
arecord -D plughw:X,0 -f S16_LE -r 16000 -d 5 -t wav test.wav   # remplace X par le numéro trouvé ci-dessus, parle pendant les 5 secondes
aplay -D plughw:X,0 test.wav                                     # tu dois t'entendre
```

Si tu ne t'entends pas ou que rien n'est enregistré, lance `alsamixer`,
appuie sur **F6** pour sélectionner explicitement `seeed2micvoicec` comme
périphérique, et vérifie qu'aucun volume n'est à 0 ou coupé (`m`).

**Pas de son après tout ça ?** Le pilote officiel évolue avec les mises à
jour du noyau Raspberry Pi OS — si la procédure ci-dessus ne fonctionne
plus telle quelle, la page officielle
([wiki Seeed Studio](https://wiki.seeedstudio.com/respeaker_2_mics_pi_hat_raspberry_v2/))
reste la référence à jour, plus fiable qu'une copie figée ici.

## Étape suivante

Le matériel et les pilotes sont prêts : passe à
[l'installation du client Jarvis](README.md#installation).

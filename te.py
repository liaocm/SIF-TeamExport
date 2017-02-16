#!/usr/bin/env python3

import os, argparse, sys, io
import PIL
import time
import numpy as np
from PIL import Image
from data import data_dict
cards = data_dict()
total_cards = len(cards) - 10 # 9 SR match cards (#10001, ..., #10009) + #0

#-------- CONFIG --------#
OUTPUT_MODE = True
SCALED_OUTPUT_PATH_PREFIX = 'output/scaled-'
JSON_OUTPUT_PATH_PREFIX = 'output/'
PEAK_THRESHOLD_RATIO = 0.96
PEAK_COMPRESSION_LENGTH = 80
IMAGE_SPACE_SCALER = 134
IMAGE_CONVERSION_SCALER = 1128 / 846
#------ END CONFIG ------#

#-------- GLOBALS --------#
normals = []
rankups = []
resolution = 4
total_time_elapsed = 0
#------ END GLOBALS ------#

def vertical_line_sum(img, pixels, ratio=4, scan_ratio = 0.0):
    width = img.size[0]
    height = img.size[1]
    result = np.zeros(int(width*scan_ratio), dtype='uint8')
    idx = np.ix_(range(height//ratio, height*(ratio-1)//ratio), 
                       range(int(width*scan_ratio), width),
                       range(0, 3))
    pixels_to_sum = pixels[idx]
    vertical_sum = np.sum(np.average(pixels_to_sum, axis=2), axis=0)
    return np.append(result, vertical_sum)

def horizontal_line_sum(img, pixels, ratio=4):
    width = img.size[0]
    height = img.size[1]
    idx = np.ix_(range(height), 
                       range(width//ratio, width*(ratio-1)//ratio),
                       range(0, 3))
    pixels_to_sum = pixels[idx]
    return np.sum(np.average(pixels_to_sum, axis=2), axis=1)

def find_peaks(sum_vec, threshold_ratio = PEAK_THRESHOLD_RATIO):
    threshold = np.amax(sum_vec) * PEAK_THRESHOLD_RATIO
    return np.nonzero(sum_vec > threshold)[0]

def compress_peaks(peaks_vec):
    res = []
    last = peaks_vec[0]
    threshold = PEAK_COMPRESSION_LENGTH
    i_s = []
    for i in range(len(peaks_vec)):
        if peaks_vec[i] - last > threshold:
            res.append(last)
            i_s.append(i)
        last = peaks_vec[i]
    return res 

def calculate_scale(compressed, num_items = 4):
    avg = 0
    for i in range(num_items):
        avg += compressed[i+1] - compressed[i]
    return IMAGE_SPACE_SCALER / avg * 4

# First, rescale image.
def rescale_image(img, pixels, output_mode = False, _scan_ratio = 0.1, output_path = 'output/default.png'):
    scale = calculate_scale(
        compress_peaks(
            find_peaks(vertical_line_sum(img, pixels, scan_ratio=_scan_ratio))))
    scaled_img = img.resize((int(img.size[0]*scale),int(img.size[1]*scale)), 
                            PIL.Image.ANTIALIAS)
    # crop the image if it is too long
    if scaled_img.size[0] / scaled_img.size[1] >= 1.5:
        new_width = int(IMAGE_CONVERSION_SCALER * scaled_img.size[1])
        scaled_img = scaled_img.crop(((scaled_img.size[0]-new_width)//4, 
                                     0, 
                                     scaled_img.size[0]-(scaled_img.size[0]-new_width)//4, 
                                     scaled_img.size[1]))
    if output_mode:
        scaled_img.save(output_path)
    return scaled_img

def get_targets(img, pixels):
    # Precondition: the image is scaled.
    # Figure out the start and end point of each team member.
    # This will be a 8 x 4 grid

    horizontal_breaks = compress_peaks(find_peaks(vertical_line_sum(img, pixels)))
    vertical_breaks = compress_peaks(find_peaks(horizontal_line_sum(img, pixels)))

    # Calculate average
    havg = 0
    vavg = 0
    for i in range(4):
        havg += horizontal_breaks[i+1] - horizontal_breaks[i]
        vavg += vertical_breaks[i+1] - vertical_breaks[i]
    havg /= 4
    vavg /= 4

    # Assuming the first point is accurate
    start = horizontal_breaks[0]
    targets = [[int(start + x * havg), int(vertical_breaks[y])] for x in range(8) for y in range(4)]
    return targets

def compare_card_at(pixels, x, y, card):
    idx = np.ix_(range(y, y+128, resolution),
                range(x, x+128, resolution),
                range(3))
    idc = np.ix_(range(0, 128, resolution),
                range(0, 128, resolution),
                range(3))
    diff = pixels[idx].astype('float')-card[idc]
    diff = diff * diff
    diff = np.sqrt(np.sum(diff, axis=2))
    diff = np.sum(np.sum(diff, axis=1), axis=0)
    return diff

def match_card_at(pixels, x, y, attr, ranked_up = 0, rarity_set = {'UR', 'SSR', 'SR'}):
    if attr == 'NONE':
        return [0, 0]
    best = [0, 0] # is_rankup, card_num
    best_val = 99999999
    for n in range(1, total_cards + 1):
        if cards[str(n)]['rarity'] not in rarity_set:
            continue
        if cards[str(n)]['attribute'] != attr:
            continue
        if ranked_up == 0:
            normal_val = compare_card_at(pixels, x, y, normals[n-1])
            if normal_val < best_val:
                best_val = normal_val
                best = [0, n]
        if ranked_up == 1:
            rankup_val = compare_card_at(pixels, x, y, rankups[n-1])
            if rankup_val < best_val:
                best_val = rankup_val
                best = [1, n]
    return best

def get_icon_color(pixels, x, y):
    idx = np.ix_(range(y+56, y+56+8),
                 range(x+1, x+9),
                 range(3))
    selected = pixels[idx]
    averaged = np.sum(np.sum(selected, axis=0), axis=0)/64
    if averaged[0]+averaged[1]+averaged[2] >= 750:
        return 'NONE'
    if averaged[0] > averaged[1] and averaged[0] > averaged[2]:
        return 'smile'
    elif averaged[1] > averaged[0] and averaged[1] > averaged[2]:
        return 'pure'
    else:
        return 'cool'

def get_icon_rankup(pixels, x, y):
    p1 = pixels[y+30][x+5].astype('float')
    p2 = pixels[y+30][x+6]
    p3 = pixels[y+31][x+5]
    p4 = pixels[y+31][x+6]
    totalr = p1[0]+p2[0]+p3[0]+p4[0]
    totalg = p1[1]+p2[1]+p3[1]+p4[1]
    totalb = p1[2]+p2[2]+p3[2]+p4[2]
    totalr /= 4
    totalg /= 4
    totalb /= 4
    if np.sqrt((totalr - 248)**2 + (totalg - 219)**2 + (totalb - 108)**2) <= 40:
        return 1
    return 0

def match_cards(pixels, targets, rarity_set = {'UR', 'SSR', 'SR'}):
    global total_time_elapsed
    team = []
    curr = 1
    start = time.time()
    print("Matching... ")
    for point in targets:
        sys.stdout.write('\r{0} / {1}'.format(curr, len(targets)))
        sys.stdout.flush()
        point_color = get_icon_color(pixels, point[0], point[1])
        point_rankup = get_icon_rankup(pixels, point[0], point[1])
        curr_card = match_card_at(pixels, point[0], point[1], 
                                  point_color, point_rankup, rarity_set)
        if curr_card[1] != 0:
            team.append(curr_card)
        curr += 1
    time_elapsed = time.time() - start
    total_time_elapsed += time_elapsed
    print('\nDone.\nTime elapsed: {0} seconds'.format(time_elapsed))
    return team

def preload_cards():
  for i in range(1, total_cards + 1):
    normals.append(
        np.array(Image.open('static/icon/normal/{0}.png'.format(str(i)))))
    rankups.append(
        np.array(Image.open('static/icon/rankup/{0}.png'.format(str(i)))))
    progress = int(i / total_cards * 100)
    sys.stdout.write("\r%d%%" % progress)
    sys.stdout.flush()
  sys.stdout.write("\n")

def main(path, rarity_set, out=False):
  global total_time_elapsed
  try:
    loading_t = time.time()
    print("Loading cards...")
    preload_cards()
    print("Done.")
    time_elapsed = time.time() - loading_t
    total_time_elapsed = time_elapsed
    print("Time elapsed: {0} seconds".format(time_elapsed))
  except BaseException:
    sys.exit("Error loading static icon data.")
    return

  try:
    img = Image.open(path)
    pixels = np.array(img)
  except BaseException:
    sys.exit("Error when loading the image.")
    return

  preprocessing_t = time.time()
  print("Preprocessing image...")
  output_path = SCALED_OUTPUT_PATH_PREFIX + os.path.basename(path)
  scaled_img = rescale_image(img, pixels, OUTPUT_MODE, output_path = output_path)
  print("Done.")
  time_elapsed = time.time() - preprocessing_t
  total_time_elapsed += time_elapsed
  print("Time elapsed: {0} seconds".format(time.time() - preprocessing_t))
  scaled_pixels = np.array(scaled_img)
  targets = get_targets(scaled_img, scaled_pixels)
  team = match_cards(scaled_pixels, targets, rarity_set)

  # Print out the team
  if out:
    print("")
    print("===========OUTPUT============")
    print("")
  i = 0
  file_output = ""
  for member in team:
    mezame = "" if member[0] == 0 else "[觉醒] "

    out_str = "{0}:　{1}{2} {3} {4}".format(
                i+1,
                mezame,
                member[1],
                cards[str(member[1])]['rarity'],
                cards[str(member[1])]['name']
              )
    file_output += out_str + "\n"
    if out:
      print(out_str)
    i += 1

  try:
    file = io.open(JSON_OUTPUT_PATH_PREFIX + os.path.basename(path) + ".out", 'w')
    file.write(file_output)
    file.close()
  except BaseException:
    sys.exit("Error writing output file.")

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument("file", help="The path to the screenshot.")
  parser.add_argument("--ur", help="Includes UR cards in the matching process.", action="store_true")
  parser.add_argument("--ssr", help="Includes SSR cards in the matching process.", action="store_true")
  parser.add_argument("--sr", help="Includes SR cards in the matching process.", action="store_true")
  parser.add_argument("--r", help="Includes R cards in the matching process.", action="store_true")
  parser.add_argument("--n", help="Includes N cards in the matching process.", action="store_true")
  parser.add_argument("--all", help="Includes all cards in the matching process.", action="store_true")
  parser.add_argument("--print-out", help="Print out the result.", action="store_true")
  parser.add_argument("--res", help="Calculate proximity vector for every RES pixels. RES should be an integer from 1 to 8, inclusive. Defaults to 4; the highest setting is 1 (most accurate, slowest).", action="store")
  args = parser.parse_args()

  if args.res:
    try:
      resolution = int(args.res)
    except BaseException:
      sys.exit("RES must be an integer between 1 and 8.")
    if resolution <= 0 or resolution > 8:
      sys.exit("RES must be an integer between 1 and 8.")

  rarity_set = set()
  if args.all:
    rarity_set = {'N', 'R', 'SR', 'SSR', 'UR'}
  if args.ur:
    rarity_set.add("UR")
  if args.ssr:
    rarity_set.add("SSR")
  if args.sr:
    rarity_set.add("SR")
  if args.r:
    rarity_set.add("R")
  if args.n:
    rarity_set.add("N")

  if len(rarity_set) == 0:
    sys.exit("Must specify at least one rarity!")

  main(args.file, rarity_set, args.print_out)
  print("Total time elapsed: {0} seconds".format(total_time_elapsed))
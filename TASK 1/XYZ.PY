import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras.applications import ResNet50
from tensorflow.keras.preprocessing.image import load_img, img_to_array
from tensorflow.keras.layers import Input, Dense, Embedding, LSTM, Add
from tensorflow.keras.models import Model
from tensorflow.keras.preprocessing.text import Tokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.callbacks import ModelCheckpoint
import matplotlib.pyplot as plt
import os
import pickle
from nltk.translate.bleu_score import sentence_bleu

# Define paths
dataset_path = 'path_to_coco_dataset'  # Update with your dataset path
images_path = os.path.join(dataset_path, 'images')
captions_path = os.path.join(dataset_path, 'captions.txt')

# Load captions
captions = pd.read_csv(captions_path, delimiter='\t', header=None)
captions.columns = ['image', 'caption']

# Preprocess captions
captions['caption'] = captions['caption'].apply(lambda x: 'startseq ' + x + ' endseq')

# Load the ResNet50 model
resnet = ResNet50(include_top=False, weights='imagenet', input_shape=(224, 224, 3), pooling='avg')
model = Model(resnet.input, resnet.output)

def extract_features(image_path):
    img = load_img(image_path, target_size=(224, 224))
    img = img_to_array(img)
    img = np.expand_dims(img, axis=0)
    img = tf.keras.applications.resnet50.preprocess_input(img)
    features = model.predict(img)
    return features

# Extract features for all images
features = {}
for img_name in os.listdir(images_path):
    img_path = os.path.join(images_path, img_name)
    features[img_name] = extract_features(img_path)

# Save features
with open('image_features.pkl', 'wb') as f:
    pickle.dump(features, f)

# Tokenize the captions
tokenizer = Tokenizer()
tokenizer.fit_on_texts(captions['caption'])
vocab_size = len(tokenizer.word_index) + 1

# Convert captions to sequences
sequences = tokenizer.texts_to_sequences(captions['caption'])
max_length = max(len(seq) for seq in sequences)

# Define model inputs
image_input = Input(shape=(2048,))
image_dense = Dense(256, activation='relu')(image_input)

caption_input = Input(shape=(max_length,))
caption_embedding = Embedding(vocab_size, 256, mask_zero=True)(caption_input)
caption_lstm = LSTM(256)(caption_embedding)

# Combine image and caption inputs
combined = Add()([image_dense, caption_lstm])
output = Dense(vocab_size, activation='softmax')(combined)

# Define the model
captioning_model = Model(inputs=[image_input, caption_input], outputs=output)
captioning_model.compile(loss='categorical_crossentropy', optimizer='adam')

captioning_model.summary()

# Prepare the data generator
def data_generator(captions, features, tokenizer, max_length, vocab_size, batch_size=64):
    X1, X2, y = [], [], []
    n = 0
    while True:
        for i, caption in captions.iterrows():
            image_id = caption['image']
            feature = features[image_id]
            seq = tokenizer.texts_to_sequences([caption['caption']])[0]
            for j in range(1, len(seq)):
                in_seq, out_seq = seq[:j], seq[j]
                in_seq = pad_sequences([in_seq], maxlen=max_length)[0]
                out_seq = to_categorical([out_seq], num_classes=vocab_size)[0]
                X1.append(feature)
                X2.append(in_seq)
                y.append(out_seq)
            n += 1
            if n == batch_size:
                yield ([np.array(X1), np.array(X2)], np.array(y))
                X1, X2, y = [], [], []
                n = 0

# Create the data generator
batch_size = 64
train_steps = len(captions) // batch_size
generator = data_generator(captions, features, tokenizer, max_length, vocab_size, batch_size)

# Train the model with checkpointing
checkpoint = ModelCheckpoint('best_model.h5', monitor='loss', save_best_only=True)
captioning_model.fit(generator, steps_per_epoch=train_steps, epochs=20, verbose=1, callbacks=[checkpoint])

# Load the best model
captioning_model.load_weights('best_model.h5')

# Generate captions
def generate_caption(model, tokenizer, photo, max_length):
    in_text = 'startseq'
    for i in range(max_length):
        sequence = tokenizer.texts_to_sequences([in_text])[0]
        sequence = pad_sequences([sequence], maxlen=max_length)
        yhat = model.predict([photo, sequence], verbose=0)
        yhat = np.argmax(yhat)
        word = tokenizer.index_word.get(yhat, None)
        if word is None:
            break
        in_text += ' ' + word
        if word == 'endseq':
            break
    return in_text

# Load a new image and generate a caption
image_path = 'path_to_new_image.jpg'  # Update with your image path
photo = extract_features(image_path).reshape((1, 2048))
caption = generate_caption(captioning_model, tokenizer, photo, max_length)
print('Generated Caption:', caption)

# Evaluate the model
def evaluate_model(model, captions, features, tokenizer, max_length):
    actual, predicted = [], []
    for i, caption in captions.iterrows():
        image_id = caption['image']
        photo = features[image_id].reshape((1, 2048))
        y_true = caption['caption'].split()
        y_pred = generate_caption(model, tokenizer, photo, max_length).split()
        actual.append([y_true])
        predicted.append(y_pred)
    print('BLEU-1:', sentence_bleu(actual, predicted, weights=(1.0, 0, 0, 0)))
    print('BLEU-2:', sentence_bleu(actual, predicted, weights=(0.5, 0.5, 0, 0)))
    print('BLEU-3:', sentence_bleu(actual, predicted, weights=(0.3, 0.3, 0.3, 0)))
    print('BLEU-4:', sentence_bleu(actual, predicted, weights=(0.25, 0.25, 0.25, 0.25)))

evaluate_model(captioning_model, captions, features, tokenizer, max_length)
